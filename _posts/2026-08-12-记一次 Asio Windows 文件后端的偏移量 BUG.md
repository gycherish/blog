---
media_subpath: /assets/img/notes
author: gycherish
title: "记一次 Asio Windows 文件后端的偏移量 BUG"
tags:
  - c++
  - asio
  - windows
  - iocp

categories:
date: 2026-08-12 21:00
---

## 问题是如何被发现的

事情是这样的，昨天我准备把一个原本只跑在 Linux 上的基于 C++23 标准的存储服务移植到 Windows 上。平台相关的代码补齐以后，编译过了，链接也过了。结果一跑测试，399 个用例挂了 17 个，进程中途还崩了一次。其中崩溃是因为编译源码依赖的 BLAKE3 库时选错了汇编变体，不过这和本文要聊的问题无关，不再详述。

把 BLAKE3 导致的问题解决后，开始认真研究 17 个运行失败的测试用例，其中有 13 个都把问题指向同一个方向：数据写入存储格式的文件后，解析器以写入时记录的大小读取时直接读到 EOF。

并且其中一个断言给了份很扎眼的数字，即第一条记录写完以后，第二条本来应该从偏移量为 48 的位置接着写，实际却落在了偏移量为 76 的位置。而 76 减 48 等于 28，28 个字节正好是那条记录的元数据的大小。

这就有意思了，文件要是被并发写坏，或者中途截断，结果通常不会这么整齐。现在多出来的空间刚好等于一段 Buffer 的长度，它更像是在提醒我，数据没有写坏，只是被放错了地方。

于是我重新看了下写文件相关的代码，存储服务在写入一条记录时会把一条记录拆成定长头部、变长元数据和载荷三个部分。由于这三个部分本身无法一次性获取到，因此为了避免拷贝就利用了 Asio 的 Scatter Write 机制（本质上是系统提供的 Scatter-Gather I/O）一次性投递三块 Buffer：

```cpp
std::array<asio::const_buffer, 3> bufs = {
    asio::buffer(header),
    asio::buffer(meta),
    asio::buffer(payload),
};

co_await asio::async_write(file, bufs, use_sender);
```

同样的代码在 Linux 上一直正常工作，结果在 Windows 上却稳定地留下空洞。怀疑对象也就从业务逻辑，一路跟到了平台相关的文件 I/O 实现。

考虑到直接在存储服务里调试这种问题太麻烦（懂的都懂）。因此，我单独写了个示例程序，先确保 Asio 的实现没有问题：

```cpp
#include <array>
#include <cstdio>
#include <string>
#include <print>
#include <asio.hpp>

int main()
{
    std::remove("out.bin");
    asio::io_context ctx;
    asio::stream_file file(ctx, "out.bin",
        asio::stream_file::write_only
        | asio::stream_file::create
        | asio::stream_file::truncate);

    const std::string a(16, 'A');
    const std::string b(28, 'B');
    const std::array<asio::const_buffer, 2> bufs{
        asio::buffer(a),
        asio::buffer(b),
    };

    asio::error_code write_error;
    std::size_t reported = 0;
    asio::async_write(file, bufs, [&](asio::error_code ec, std::size_t n) {
        write_error = ec;
        reported = n;
    });

    ctx.run();
    file.close();

    if (write_error) {
        std::println("write failed: {}", write_error.message());
        return 1;
    }

    std::FILE* in = std::fopen("out.bin", "rb");
    if (!in) return 1;

    std::fseek(in, 0, SEEK_END);
    const long on_disk = std::ftell(in);
    std::fclose(in);

    std::println("reported {}, on disk {} (expected 44)", reported, on_disk);
    return 0;
}
```

本次移植使用的是 MSYS2 下的 MinGW64 工具链，在 MSYS2 的 MinGW64 Shell 环境下编译执行，结果如下：

```bash
$ g++ -std=c++23 -I/d/repo/asio-github/include -DASIO_HAS_FILE test.cpp -lws2_32 -lmswsock -lstdc++exp -static -o test
$ ./test.exe
reported 44, on disk 72 (expected 44)
```

可以看到，看起来不应该出问题的代码，竟然直接复现了。本来还想着要是存储服务的问题又够折腾我一段时间了，结果现在直接把问题指向了 Asio！那么，为什么会这样？

## 问题原因

为了看看到底写了什么，我用十六进制工具打开文件（Windows 下推荐 [ImHex](https://imhex.werwolv.net/)），内容很直白：开头是 16 个 `'A'`，中间夹着 28 个零字节，然后是 28 个 `'B'`。基于我对 Asio 的熟悉程度，我这里没有实际进行调试，顺着调用链翻了下 Asio 的源码，基本就确定问题原因了：

`asio::stream_file` 提供的是流式接口，文件的读写偏移由 Asio 内部实现维护，保存在 `win_iocp_file_service::implementation_type::offset_` 里。[`win_iocp_file_service.hpp`](https://github.com/chriskohlhoff/asio/blob/8806a6803cde7054c3049d3666d3ec36786568c5/include/asio/detail/win_iocp_file_service.hpp) 的 185 行在投递异步 IO 操作前先取出当前位置，再按照整个 Buffer Sequence 的大小推进 `offset_`。

```cpp
uint64_t offset = impl.offset_;
impl.offset_ += asio::buffer_size(buffers);
handle_service_.async_write_some_at(impl, offset, buffers, handler, io_ex);
```

无论怎么看，这段代码都没什么问题。虽然调用方传进来一组 Buffer，但是 API 的语义是明确的，即这组 Buffer 是以整体的形式完成或失败（严格来讲还有部分成功的情况）。因此，内部实现提前以操作完成来推进 `offset_` 并没有什么问题。

但是 [`win_iocp_handle_service.hpp`](https://github.com/chriskohlhoff/asio/blob/8806a6803cde7054c3049d3666d3ec36786568c5/include/asio/detail/win_iocp_handle_service.hpp) 的 173 行在收到整个序列以后，却只取第一个非空 Buffer 交给 `start_write_op`：

```cpp
start_write_op(impl, 0,
  buffer_sequence_adapter<asio::const_buffer,
    ConstBufferSequence>::first(buffers), o);
```

问题就出在这两段代码之间：上面那层认为本次操作会处理整个序列，于是 `offset_` 按全部长度推进。而下面那层实际只提交了第一个非空 Buffer。

当然，只写第一个 Buffer 并不违反 Stream 的要求。Stream 本来就允许短写，Asio 的 [`async_write`](https://think-async.com/Asio/asio-1.18.2/doc/asio/overview/core/streams.html) 会反复调用 `async_write_some`，直到整个序列都处理完。但下一次调用从哪里继续，取决于 `offset_`。

回到上面的示例代码，实际写入流程是这样的：

| 调用 | 传入的剩余序列 | 实际提交 | 写入偏移 | 调用后的 `offset_` |
|---|---:|---:|---:|---:|
| 第一次 | 16 + 28 | 16 | 0 | 44 |
| 第二次 | 28 | 28 | 44 | 72 |

第一次调用只写了 16 字节，`offset_` 却已经从 0 跳到了 44。`async_write` 接着处理余下的 28 字节时，只能从 44 开始。中间空出来的，刚好是 28 字节。

这也解释了另一个看着很反常的现象。`async_write` 汇总的是两次调用实际完成的字节数，所以回调依然会报告 44。Asio 没有撒谎，只是这个数字完全看不出流位置已经走错了。

## 为什么 Linux 没问题

这里涉及到一个核心问题：Scatter-Gather I/O 在各个平台上的实现并不一致。

Windows 普通的 `WriteFile` 和 `ReadFile` 每次只接收一块连续缓冲区。系统确实还提供了 `WriteFileGather` 和 `ReadFileScatter`，但根据 Microsoft 的 [`WriteFileGather`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-writefilegather) 文档，句柄必须同时带有 `FILE_FLAG_OVERLAPPED` 和 `FILE_FLAG_NO_BUFFERING` 标志。每个缓冲区至少占一个内存页，还要按页边界对齐。因为启用了 Unbuffered I/O（Direct IO），总字节数也得满足扇区对齐要求。

然而，除了类似数据库系统，大部分应用程序不会随便使用 `FILE_FLAG_NO_BUFFERING`，一方面没必要，另一方面会导致性能变差。因此，作为通用的 IO 库，不适配这种功能是可以理解的。所以 Asio 的 IOCP 文件后端每次只提交序列中的第一个 Buffer，再让组合操作处理剩余部分，这个取舍是合理的。偏移只要跟着本次提交量往前推进，逻辑就不会出问题。

相比文件 IO 存在这种不一致的地方，Windows 网络 IO 那边就轻松多了。`win_iocp_socket_service_base` 调用的 `WSASend` 可以接收 `WSABUF` 数组，一次提交整个序列，天然支持 Scatter-Gather I/O，跟 POSIX 那边的行为基本一致。

相比 Windows 下文件 IO 和网络 IO 在 Scatter-Gather I/O 实现上的不统一，Linux 则没有这种问题。Linux 平台无论同步 IO(`readv`/`writev`) 还是异步 IO(libaio 的 `io_prep_preadv`/`io_prep_pwritev`，io_uring 的 `io_uring_prep_readv`/`io_uring_prep_writev`) 都完整支持 Scatter-Gather I/O。

回到上面的 `asio::async_write` 的问题，Linux 对应的实现在 [io_uring_descriptor_service](https://github.com/chriskohlhoff/asio/blob/8806a6803cde7054c3049d3666d3ec36786568c5/include/asio/detail/io_uring_descriptor_service.hpp) 的 330 行：

```cpp
start_op(impl, io_uring_service::write_op, p.p, is_continuation,
  buffer_sequence_adapter<asio::const_buffer,
    ConstBufferSequence>::all_empty(buffers));
```

可以看到，Linux 这边投递 IO 请求时是把所有的 Buffer 都带上了，而不是像 Windows 那样只投递第一个。我猜测，这跟 Windows 的非 Direct 文件 IO 不支持 Scatter-Gather I/O 有关，导致 Asio 的作者在做出妥协的同时忽视了对偏移的处理（也可能作者清楚地知道问题所在而故意不处理，毕竟想使用 Asio 的异步 IO 功能需要显式开启 ASIO_HAS_FILE 宏定义，并且一次投递多块 Buffer 的场景并不是很多）。

## 影响范围

上文贴出的都是异步文件 IO 的相关的代码，实际上同步 IO 也存在这个问题，具体原理类似，不再详述，有兴趣的可以自己看代码。

截至 2026 年 8 月 12 日，这个问题在官方代码中依然没有解决。因此，为了规避这个问题，应用层可以通过避免一次投递多块 Buffer 来规避这个问题。

## 解决方案

经过认真思考，其实解法很简单，我已经给官方提了 [PR](https://github.com/chriskohlhoff/asio/pull/1762)。有兴趣的可以看相关修改记录，本文不再赘述。

不过在提 PR 前本来准备先创建 Issue 的，但是经过搜索才发现 [Issue #1346](https://github.com/chriskohlhoff/asio/issues/1346) 早在 2023 年 8 月 25 日就报告过同一件事。报告者写入三个 10 字节 Buffer，Linux 上得到连续的 `a`、`b`、`c`，Windows 上却在三段数据之间留下空白。看到这个 BUG 的日期，我的 PR 大概率也是不会合并的，就这样吧！

## 番外篇

其实本文没有触及 Asio 底层异步 IO 框架的核心，虽然贴了几行代码能看出 BUG 的大概原因，但是 `offset_` 在后续的调用中如何被改变的依然看不出来。本人一直想写 Asio 的源码解析系列，但是苦于涉及知识面太广、时间精力有限一直没有开始，这里先立个 Flag，后面有时间一定开更（带上我的 AI 助理一起干）。

另外再说一点，Asio 的异步文件 IO 只支持 io_uring，对于较低的 Linux 内核版本是无法使用的，为此，我为其添加了 libaio 的支持，有兴趣的可以看下我在 [Gitee](https://gitee.com/gycherish/asio.git) 中的 fork 版本的提交，相关内容包括本次 BUG 修复都在 v1.38.2 分支上。
