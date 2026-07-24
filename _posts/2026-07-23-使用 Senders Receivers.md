---
media_subpath: /assets/img/notes
author: gycherish
title: "使用 Senders/Receivers"
slug: using-senders-receivers
tags:
  - c++
  - concurrency
  - sender-receiver
  - execution
categories:
date: 2026-07-23 21:00
original_author: Lucian Radu Teodorescu
original_url: https://accu.org/journals/overload/33/185/teodorescu/
original_date: 2025-02
---

> 译者说明：本文译自 Lucian Radu Teodorescu 发表于 ACCU *Overload* 185 的 [《Using Senders/Receivers》](https://accu.org/journals/overload/33/185/teodorescu/)。示例使用写作时的 NVIDIA stdexec，其中 `exec` 命名空间下的部分设施不属于 P2300R10，个别接口当时仍在标准化过程中。译文保留原文的版本语境和作者指出的已知问题，同时校正了代码中明显的拼写和标点错误，并收紧了少数过强的技术结论。

本文是 [《Senders/Receivers 入门》](/blog/posts/senders-receivers-an-introduction/) 的续篇。上一篇介绍了即将进入 C++26 的 Senders/Receivers 框架，重点放在基本概念和标准化范围；这一篇将展示如何用它构建并发应用程序。

我们不再停留在最小示例，而是讨论三个更接近实际软件的问题：计算 Mandelbrot 分形、实现并发排序，以及批量读取图像、添加图形效果后写入另一个目录。这三类任务都能从多线程执行中获益。

全部示例代码可以在 [GitHub](https://github.com/lucteo/overload185_sr_examples) 找到。本文使用 Senders/Receivers 提案的参考实现 [stdexec](https://github.com/NVIDIA/stdexec)。示例还用到了一些当时尚未被标准委员会接受的功能，希望它们以后能够进入标准。

## 开始之前

在进入实际案例前，先用一个最小示例做好准备。代码清单 1 从主线程以外的另一个线程输出 `Hello, concurrency!`。

```cpp
#include <exec/system_context.hpp>
#include <stdexec/execution.hpp>

int main() {
  stdexec::scheduler auto sched = exec::get_system_scheduler();
  stdexec::sender auto snd =
      stdexec::schedule(sched)
      | stdexec::then([] {
          printf("Hello, concurrency!\n");
        });
  stdexec::sync_wait(std::move(snd));
}
```

*代码清单 1*

它大致等价于：

```cpp
std::thread{[] {
  printf("Hello, concurrency!\n");
}}.join();
```

程序从系统调度器取得一个线程，在该线程上执行 lambda，并将消息输出到标准输出。

调度器是**执行上下文（execution context）**的句柄。执行上下文拥有实际执行工作的线程，例如 CPU 线程或 GPU 线程。系统调度器代表当前系统的默认执行上下文，预计由系统上运行的多个应用程序共享。可以把它理解成一个线程数量未指定、由多个应用共享的线程池。

待执行的工作由 Sender `snd` **描述**。上一篇提到，Sender 只描述工作，并不代表工作已经开始执行。Sender 必须启动，工作才会发生。它有些像 `std::function` 对象：对象表示一段类似函数的工作，但仅仅定义对象不会执行函数，还要显式调用它。本例通过 `sync_wait` 启动 Sender 描述的工作，阻塞等待结果，然后返回工作结果，只是这里没有使用返回值。

从示例可以看到，stdexec 提供 `stdexec` 和 `exec` 两个命名空间，头文件也按这两个名称组织。`stdexec` 命名空间下的内容属于已经进入 C++26 草案的 [P2300](https://wg21.link/P2300R10)。`exec` 中的实体不属于最初的 P2300，它们要么是标准化候选项，要么是实用扩展。这里使用的 `system_context` 和 `get_system_scheduler` 当时由 [P2079R5](https://wg21.link/P2079R5) 提议标准化。

## 工作图

串行程序依次执行指令，执行顺序通常很直接。特别是在遵守结构化编程原则时，理解对象和代码结构的作用域十分重要。

并发程序除了要考虑实体的作用域，还要考虑指令顺序。并发执行中的工作项只有**偏序关系**，它们形成一张图，表示彼此依赖和执行流向。

观察这张工作图会发现，结构良好的并发代码通常让一项操作的作用域与它可能执行的时间跨度相吻合。这个跨度从所有前驱完成开始，到任一后继启动为止。

把工作看成图，可以迅速理解问题中的约束。后面的每个案例都会简要分析对应的执行图。

## 计算 Mandelbrot 集

Mandelbrot 集是结构非常复杂的二维分形，由简单的迭代公式 `f_c(z) = z^2 + c` 的收敛情况生成。图 1 的 Mandelbrot 分形以 `c = -1.4011` 为中心，虚部为 0，缩放比例为 512，迭代上限（深度）为 1000。不同迭代次数使用不同颜色表示。

![Mandelbrot 分形](using-senders-receivers-mandelbrot.png)

*图 1*

不使用并发时，计算这张分形图的代码大致如代码清单 2 所示。

```cpp
int mandelbrot_core(std::complex<double> c, int depth) {
  int count = 0;
  std::complex<double> z = 0;
  for (int i = 0; i < depth; i++) {
    if (abs(z) >= 2.0)
      break;
    z = z * z + c;
    count++;
  }
  return count;
}

std::complex<double> pixel_to_complex(int x, int y) {
  double x0 = offset_x + (x - max_x / 2) * 4.0 / max_x / scale;
  double y0 = offset_y + (y - max_y / 2) * 4.0 / max_y / scale;
  return std::complex<double>(x0, y0);
}

template <typename F>
void serial_mandelbrot(int* vals, int max_x,
  int max_y, int depth, F&& transform) {
  for (int y = 0; y < max_y; y++) {
    for (int x = 0; x < max_x; x++) {
      vals[y * max_x + x] =
          mandelbrot_core(transform(x, y), depth);
    }
  }
}
```

*代码清单 2*

程序使用一个 `max_x × max_y` 的矩阵，每个元素保存一个深度值，随后将深度映射成颜色，生成彩色图像。传给 `serial_mandelbrot` 的 `transform` 函数对象负责把矩阵位置，也就是像素，转换成复数；`pixel_to_complex` 是一种可能的实现。算法核心在 `mandelbrot_core` 中，它为给定的初始复数 *c* 计算深度，最高不超过指定上限。矩阵中的每个元素都会调用这个函数，每次最多迭代 `depth` 次。

算法的整体复杂度是 *O(max_y × max_x × depth)*。有些像素调用 `mandelbrot_core` 后只需几次迭代就会结束，因此矩阵各元素的计算量并不均衡。即便如此，在常见硬件上，以 1000 的深度填满一屏 Mandelbrot 分形仍然不算快。并发计算有望显著改善性能。

代码清单 3 展示了怎样把主函数改成多线程版本。主要变化是将遍历 *y* 轴的外层循环改成 `bulk()`。`bulk()` Sender 在当前执行上下文中执行 `max_y` 次函数体。执行上下文仍由 `get_system_scheduler()` 取得的调度器提供，因此矩阵的不同行可以由不同线程计算。

```cpp
template <typename F>
void mandelbrot_concurrent(int* vals, int max_x,
  int max_y, int depth, F&& transform) {
  auto sched = exec::get_system_scheduler();
  auto snd = stdexec::schedule(sched)
    | stdexec::bulk(max_y, [=](int y) {
      for (int x = 0; x < max_x; x++) {
        vals[y * max_x + x] =
            mandelbrot_core(transform(x, y), depth);
      }
    });
  stdexec::sync_wait(std::move(snd));
}
```

*代码清单 3*

为了便于讨论，假设运行程序的机器有 8 个核心，系统执行上下文也提供 8 个操作系统线程。具体线程数量由实现决定，并不由 Sender 接口保证。线程数超过硬件线程数会造成 CPU [过度订阅](https://en.wikipedia.org/wiki/Resource_contention)，反而降低应用性能。

工作本身由 Sender `snd` 描述。程序调用 `sync_wait()` 开始执行，并阻塞到全部工作结束。

这个例子有一个需要特别说明的地方。只看代码清单 3，读者可能会认为 `bulk()` 的定义本身就规定了计算何时可以并发执行，事实并非如此。默认情况下，`bulk()` 只是一个更漂亮的 `for` 循环，自身不包含并发能力。

并发来自特化。`bulk()` 之类的算法可以针对当前调度器进行特化。本例中，系统调度器为 `bulk()` 提供特化，利用它管理的执行上下文并行运行。系统调度器与 `bulk()` 结合，才得到我们想要的多线程实现。去掉系统调度器，计算就会顺序执行。

图 2 展示了这个问题的工作依赖。从并发角度看，它比较简单，工作图并不复杂。

![Mandelbrot 计算的工作图](using-senders-receivers-mandelbrot-work-graph.svg)

*图 2*

可以看到，使用 Senders/Receivers 将单线程代码改成多线程，并不一定很困难。

## 并发排序

上一个例子只需把 `for` 循环改成 `bulk()`。迭代次数已知时，`bulk()` 可以按照当前调度器的规则并发执行工作。但如果任务不是线性的，迭代次数也无法提前确定，又该怎么办？下面用并发排序回答这个问题。

我们将经典快速排序改成并发执行。代码清单 4 是串行版本。数据量较小时，以 `std::sort` 作为递归的基本情况；数据量较大时，根据一个**枢轴（pivot）**将元素分成三组：小于枢轴、等于枢轴和大于枢轴。枢轴的选择会尽量提高分区均衡的概率。完成分区后，再递归排序较小和较大的两个分区。

```cpp
template <std::random_access_iterator It>
void serial_sort(It first, It last) {
  auto size = std::distance(first, last);
  if (size_t(size) < size_threshold) {
    // Use serial sort under a certain threshold.
    std::sort(first, last);
  } else {
    // Partition the data, such as elements
    // [0, mid1) < [mid1, mid2) <= [mid2, n).
    // Elements in [mid1, mid2) are equal to
    // the pivot.
    auto p = sort_partition(first, last);
    auto mid1 = p.first;
    auto mid2 = p.second;
    serial_sort(first, mid1);
    serial_sort(mid2, last);
  }
}
```

*代码清单 4*

代码清单 5 使用 Senders/Receivers 实现并发版本。示例利用 `async_scope` 管理动态产生的并发工作，因此需要为递归函数加一层包装。`async_scope` 为它启动的并发任务提供动态作用域。排序函数的核心逻辑基本不变，主要区别是右侧子区间会提交到系统调度器，与左侧子区间并发排序。

```cpp
template <std::random_access_iterator It>
void concurrent_sort_impl(It first, It last, exec::async_scope& scope) {
  auto size = std::distance(first, last);
  if (size_t(size) < size_threshold) {
    // Use serial sort under a certain threshold.
    std::sort(first, last);
  } else {
    // Partition the data, such as elements
    // [0, mid1) < [mid1, mid2) <= [mid2, n).
    // Elements in [mid1, mid2) are equal to the
    // pivot.
    auto p = sort_partition(first, last);
    auto mid1 = p.first;
    auto mid2 = p.second;

    // Spawn work to sort the right-hand side.
    stdexec::sender auto snd =
      stdexec::schedule(exec::get_system_scheduler())
      | stdexec::upon_error(
          [](std::error_code ec) -> void {
            throw std::runtime_error("cannot start work");
          })
      | stdexec::then([=, &scope] {
          concurrent_sort_impl(mid2, last, scope);
      });
    scope.spawn(std::move(snd));

    // Execute the sorting on the left side,
    // on the current thread.
    concurrent_sort_impl(first, mid1, scope);
  }
}

template <std::random_access_iterator It>
void concurrent_sort(It first, It last) {
  exec::async_scope scope;
  concurrent_sort_impl(first, last, scope);
  stdexec::sync_wait(scope.on_empty());
}
```

*代码清单 5*

启动工作的代码看起来更复杂，因为它还要处理 `std::error_code`。系统调度器当时仍在标准化，stdexec 也在持续跟进相关变化。写作本文时，在系统执行上下文中调度工作可能产生 `std::error_code`；`async_scope` 却不能直接处理这类错误，只能管理异常。为弥合差异，代码使用 `upon_error()` 将 `std::error_code` 转换成异常。

理想情况下，传给 `upon_error()` 的 lambda 返回值会通过值通道发送。`schedule()` 的值通道是 `set_value(void)`，我们不希望加入额外的值通道，因此 lambda 必须返回 `void`。即使 lambda 函数体为空，它也没有声明为 `noexcept`。`upon_error()` 会据此认为 lambda 可能抛出异常，并在结果中加入 `set_error(std::exception_ptr)` 错误通道。这样就能把 `set_error(std::error_code)` 转换成 `set_error(std::exception_ptr)`。后文还会介绍另一种修改 Sender 错误通道的方法。

即使 `std::error_code` 错误通道最终没有标准化，stdexec 也删除了相应支持，这个练习仍然有助于理解错误通道的处理方式。

这个例子最值得讨论的是工作的时间跨度。之前的例子中，启动工作的跨度始终包含在外围函数的跨度内，二者完全嵌套，这叫作**结构化并发**。代码清单 5 启动的工作却可能活到外围函数返回以后，作用域并不完全嵌套，我们称之为**弱结构化并发**。

`async_scope` 的重要作用之一，是为原本缺乏结构的工作添加弱结构。它要求所有工作必须在 `stdexec::sync_wait(scope.on_empty())` 返回前完成。这条语句阻塞当前线程，直到作用域中的工作全部结束，也就是作用域变空。

可以把 `async_scope` 看成一个功能更完整的共享计数器。每当作用域启动一项工作，计数器加一；工作完成后，计数器减一。`on_empty()` 返回一个 Sender，当计数归零、没有待完成工作时，这个 Sender 才会完成。

只要引入弱结构化构造，就必须重新检查其安全性。尤其要确认，启动的工作不会访问外围函数栈中已经销毁的对象。本例启动的工作只访问输入序列中的某个区间，而且不会有其他工作项同时访问同一区间。

并发排序无法并行完成分区，但分区后会不断把任务对半拆分，并发处理各个区间。参与排序的工作线程会逐渐增加，直到系统调度器中的所有线程都得到充分利用。

图 3 展示了这个问题的并发结构，体现了它的递归性质，以及任务如何拆分并发执行。

![并发排序的工作图](using-senders-receivers-concurrent-sort-work-graph.svg)

*图 3*

这个例子展示了弱结构化并发的用法，也说明了管理错误通道时可能遇到的问题。

## 处理图像

现在来看一个更复杂的问题。程序从一个目录读取全部 JPEG 图像，为每张图像应用滤镜，再将结果保存到另一个目录。图像处理可能很耗时，需要处理的文件也可能很多，因此多线程可以显著改善性能。

代码清单 6 给出了函数声明和 `main()` 的基本轮廓。程序使用 [OpenCV](https://opencv.org/) 处理图像。所有返回 `cv::Mat` 的普通函数都会处理图像并返回新图像；`read_file` 和 `write_file` 分别负责文件读取与写入。后文重点讨论 `tr_cartoonify`、`error_to_exception` 和 `process_files`。

```cpp
cv::Mat tr_apply_mask(const cv::Mat& img_main, const cv::Mat& img_mask);
cv::Mat tr_blur(const cv::Mat& src, int size);
cv::Mat tr_to_grayscale(const cv::Mat& src);
cv::Mat tr_adaptthresh(const cv::Mat& img, int block_size, int diff);
cv::Mat tr_reducecolors(const cv::Mat& img, int num_colors);
cv::Mat tr_oilpainting(const cv::Mat& img, int size, int dyn_ratio);
auto tr_cartoonify(const cv::Mat& src, int blur_size,
  int num_colors, int block_size, int diff);
auto error_to_exception();
std::vector<std::byte> read_file(const fs::directory_entry& file);
void write_file(const char* filename, const std::vector<unsigned char>& data);
exec::task<int> process_files(const char* in_folder_name, const char* out_folder_name,
  int blur_size, int num_colors, int block_size, int diff);

int main() {
  auto everything = process_files("data", "out", blur_size, num_colors, block_size, diff);
  auto [processed] = stdexec::sync_wait(std::move(everything)).value();
  printf("Processed images: %d\n", processed);
  return 0;
}
```

*代码清单 6*

图 4 假设有三个文件需要处理，展示了对应的执行图。它看起来像一条流水线：首尾的 `read_file` 和 `write_file` 是 I/O 操作，中间则是适合在多个线程上并发执行的处理步骤。

![图像处理流水线](using-senders-receivers-image-pipeline.svg)

*图 4*

### 为小型流水线加入并发

“卡通化”操作会把蒙版应用到减少颜色后的图像上，蒙版则由原图的边缘组成。生成最终结果需要两张中间图像：一张减少颜色，一张显示边缘。减少颜色的图像由 `tr_reduce_colors` 产生；边缘图像则依次调用 `tr_blur`、`tr_to_grayscale` 和 `tr_adaptthresh`。这些操作可能很耗时，两条处理流又彼此独立，适合并发执行。代码清单 7 展示了具体写法。

```cpp
auto tr_cartoonify(const cv::Mat& src, int blur_size, int num_colors,
  int block_size, int diff) {
  auto sched = exec::get_system_scheduler();
  stdexec::sender auto snd = stdexec::when_all(
    stdexec::transfer_just(sched, src)
    | error_to_exception()
    | stdexec::then([=](const cv::Mat& src) {
        auto blurred = tr_blur(src, blur_size);
        auto gray = tr_to_grayscale(blurred);
        return tr_adaptthresh(gray, block_size, diff);
    }),
    stdexec::transfer_just(sched, src)
    | error_to_exception()
    | stdexec::then([=](const cv::Mat& src) {
        return tr_reducecolors(src, num_colors);
    }))
    | stdexec::then(
      [](const cv::Mat& edges,
        const cv::Mat& reduced_colors) {
        return tr_apply_mask(reduced_colors, edges);
    }
  );
  return snd;
}
```

*代码清单 7*

这里再次依赖系统调度器实现并发。传给 `when_all()` 的两个参数分别代表一条并发计算链。每条链都从 `transfer_just()` 开始：它把执行转移到系统调度器管理的线程，同时把源图像作为参数传入。`std::error_code` 错误通道仍然存在，这次通过接入 `error_to_exception()` Sender 适配器处理。两条计算链的主要工作都写在传给 `then()` 的 lambda 中，清楚地展示了两张中间图像的生成步骤。

`when_all()` 合并两项计算，只有两个分支都结束，所得 Sender 才会完成。完成时，它通过值通道发出两张结果图像。随后再用一个 `then()` 将两张图像合成最终输出。整个结果是一个以最终图像作为值完成的 Sender，也可能通过异常形式的错误或停止信号完成。

`tr_cartoonify()` 直接返回这个 Sender。它封装了全部内部 Sender 和 lambda 的类型信息，类型非常复杂，很难显式命名。

这项图像处理中的并发程度有限，提升不到两倍，但与串行版本相比仍有可观收益。

### 归并错误完成信号

下面看代码清单 8 中的 `error_to_exception()`。它与上一节使用 `upon_error()` 的目标基本相同，但写法更通用。`upon_error()` 在一些场景下不够方便：它无法处理前一个 Sender 的多种错误完成信号，而且返回值类型必须与流水线正确衔接。

```cpp
auto error_to_exception() {
  return stdexec::let_error([](auto e) {
    if constexpr (std::same_as<decltype((e)), std::exception_ptr>) {
      return stdexec::just_error(e);
    } else {
      return stdexec::just_error(
        std::make_exception_ptr(std::runtime_error("other error"))
      );
    }
  });
}
```

*代码清单 8*

这段代码把任意错误类型转换成异常。前一个 Sender 每发出一次错误，传给 `let_error()` 的 lambda 就会调用。如果前一个 Sender 同时支持 `set_error(std::exception_ptr)` 和 `set_error(std::error_code)`，lambda 必须既能接收 `std::exception_ptr`，也能接收 `std::error_code`，所以这里使用泛型 `auto` 参数。

Lambda 内部区分两种情况：参数是异常指针时直接转发，否则创建并转发一个新异常。

两个分支都返回产生错误的 Sender，而且返回类型必须相同，否则代码无法通过编译。

不熟悉完成信号转换的用户可能会觉得这套过程有些繁琐，经过练习后应当能很快适应这些模式。

### 主处理流程

代码清单 9 是 `process_files()` 的主体，也是程序的核心流程。暂且放下它使用协程这一点，也先忽略函数开头两个调度器和 `async_scope` 的初始化，循环本身很直接：遍历源目录中的全部 JPEG 图像，逐个处理。每个文件的工作又分成两部分，读取文件内容和处理图像。

```cpp
exec::task<int> process_files(const char* in_folder_name, const char* out_folder_name,
  int blur_size, int num_colors, int block_size, int diff) {
  exec::async_scope scope;
  exec::static_thread_pool io_pool(1);
  auto io_sched = io_pool.get_scheduler();
  auto cpu_sched = exec::get_system_scheduler();
  int processed = 0;

  for (const auto& entry : fs::directory_iterator(in_folder_name)) {
    auto extension = entry.path().extension();
    if (!entry.is_regular_file() || (extension != ".jpg" && extension != ".jpeg")) {
      continue;
    }

    auto in_filename = entry.path().string();
    auto out_filename = (fs::path(out_folder_name) / entry.path().filename()).string();
    printf("Processing %s\n", in_filename.c_str());

    auto file_content = co_await (
      stdexec::schedule(io_sched)
      | stdexec::then([=] {
        return read_file(entry);
      })
    );
    stdexec::sender auto work = ...;
    scope.spawn(std::move(work));
  }

  co_await scope.on_empty();
  co_return processed;
}
```

*代码清单 9*

读取文件只需在 `io_sched` 调度器的上下文中调用 `read_file()`。使用该调度器的原因会在下一节解释。这里还出现了 `co_await`，稍后也会讨论。

代码清单 10 展示了主要的图像转换。输入文件内容先转移到 `cpu_sched`，也就是系统调度器，绝大多数处理都在这里完成。与前面的例子相同，流水线通过 `error_to_exception()` 归并错误通道。随后在 CPU 线程中调用 `cv::imdecode()` 解码图像。

```cpp
stdexec::sender auto work = stdexec::transfer_just(cpu_sched,
  cv::_InputArray::rawIn(file_content))
  | error_to_exception()
  | stdexec::then([=](cv::InputArray file_content) -> cv::Mat {
    return cv::imdecode(file_content, cv::IMREAD_COLOR);
  })
  | stdexec::let_value([=](const cv::Mat& img) {
    return tr_cartoonify(
      img, blur_size, num_colors, block_size, diff);
  })
  | stdexec::then([=](const cv::Mat& img) {
    std::vector<unsigned char> out_image_content;
    if (!cv::imencode(extension, img, out_image_content)) {
      throw std::runtime_error("cannot encode image");
    }
    return out_image_content;
  })
  | stdexec::continues_on(io_sched)
  | stdexec::then([=](const std::vector<unsigned char>& bytes) {
    write_file(out_filename.c_str(), bytes);
  })
  | stdexec::then([=] {
    printf("Written %s\n", out_filename.c_str());
  })
  | stdexec::then([&] {
    processed++;
  }
);
```

*代码清单 10*

取得图像后，程序应用 `tr_cartoonify()` 转换。这里没有使用常见的 `then()`，而是使用 `let_value()`。函数对象返回普通值时用 `then()`，返回 Sender 时则用 `let_value()`。`tr_cartoonify()` 返回 Sender，因此必须选择 `let_value()`。这个算法用途很广，是 Sender 的 monadic bind 操作。

转换结束后，程序调用 `cv::imencode()` 将图像重新编码成 JPEG 字节流。这通常是 CPU 密集型操作，所以仍在 CPU 线程中完成。接着需要把字节流写入磁盘。写文件属于 I/O 操作，流水线会转移到专门处理 I/O 的调度器。写入结束后，程序仍在 I/O 线程输出一条消息，并递增成功处理的图像计数。

### 订阅不足与过度订阅

某些现代计算机上的 I/O 很快，也可能消耗大量 CPU。这里假设情况并非如此：图像读写速度较慢，却不太占用 CPU。为便于讨论，再假设 I/O 占程序总运行时间的 25%。

如果不考虑这一点就直接加入并发，CPU 核心会先处理图像，然后在大约 25% 的时间里空闲等待 I/O。多个线程上的 I/O 操作还可能相互干扰；并发程度越高，性能下降反而越明显。

常见解决办法是构造一条流水线，让所有 I/O 操作在一个线程上执行，CPU 密集型工作则分配到大小与物理核心数量相当的线程池。为此，示例使用 `static_thread_pool` 提供的调度器专门处理 I/O。注意，`static_thread_pool` 并未提议标准化。这个调度器与按照可用硬件资源配置的系统调度器相互独立。

假设目标硬件有 *N* 个物理核心，为什么不直接使用 *N* + 1 个线程？原因在于过度订阅：系统的物理核心较少，却同时运行更多 CPU 密集型任务，会因为频繁切换任务而降低性能。

一种常见误解是，在单个核心上同时运行两个各需一秒的任务，能让它们在一秒内一起结束。实际情况通常相反，线程切换本身有成本，两个任务并发运行往往超过两秒，顺序执行反而更快。我在 ACCU 2023 的[《Concurrency Approaches: Past, Present, and Future》](https://www.youtube.com/watch?v=uSG240pJGPM)演讲中讨论过这个问题。可以想象一下同时阅读两本书，或者让外科医生一边做复杂手术，一边打电话参加医院董事会。单个物理核心同时处理两项任务，就要不断切换上下文，而这种切换并不便宜。

为了获得良好性能，理想状态是程序运行期间所有核心的 CPU 利用率都接近 100%。低于 100% 时会出现**订阅不足（undersubscription）**，有工作可做却仍有核心空闲；工作量超过 100% 时则会频繁切换任务，处理器把本可用于关键工作的时间花在上下文切换上。

因此，常见做法是把 I/O 从 CPU 密集型工作中分离出来，交给专用执行引擎。

### 协程与 Sender

这个例子还展示了 Senders/Receivers 与协程的配合方式。只需给协程类型添加少量标注，协程就能表现得像 Sender：既可以 `co_await` 一个 Sender，也可以在需要 Sender 的地方使用协程对象。

stdexec 提供了这样的协程类型 `exec::task`，`process_files()` 正是用它定义的协程。协程先在 I/O 执行上下文中 `co_await` 输入文件的读取结果，随后又通过 `scope.on_empty()` 等待全部活动完成。另一端的 `main()` 把协程对象传给 `sync_wait()`，说明 Sender 算法可以直接使用协程。

本例的 `process_files()` 从主线程开始执行。第一次 `co_await` 后，执行转移到 I/O 线程；协程结束时仍停留在 I/O 线程。最后，`sync_wait()` 让主执行路径回到主线程。

写作时，我发现代码中有一个 bug。我决定保留并解释它，这对读者可能更有帮助。问题在于，离开协程作用域时会销毁 `io_pool`，但它的某个线程上可能仍有代码正在执行。理想情况下，销毁线程池前应先切回主线程。也可以将控制权交给一个 CPU 线程，因为系统调度器保证其线程在应用程序的整个生命周期内都有效，包括 `main()` 开始之前和结束之后。

再回到协程。协程与 Sender 的表达能力有很大重叠，二者也能互相配合。哪一种效率更高，取决于任务结构、算法、调度器和具体实现。我认为协程在两类场景中尤其有用：

- **非线性控制流**：逻辑中出现循环或分支时，Sender 因为缺少这类模式的标准算法，表达起来会比较困难。即使以后标准化了相应算法，把所有逻辑都写成表达式组合，仍可能比传统控制结构更繁琐；
- **类型擦除**：当时还没有提议标准化的类型擦除 Sender，这意味着 Sender 的内部结构必须在使用位置完全可见。协程天然能够隐藏实现细节，适合需要类型擦除的场景。

写作本文时，示例中的 `task` 类型尚未正式提出标准化，不过大家普遍认同它值得进入标准。

## 要点回顾

上一篇文章介绍了已经进入 C++26 工作草案的 Senders/Receivers 框架，本文则通过三个案例帮助读者熟悉实际写法。每个案例都试图通过多线程提高性能。

这些例子表明，为应用程序加入多线程不必令人望而生畏。把问题看成执行图，可以清楚、直观地表达并发解法，并减少直接操作易错同步原语的需要。

使用 Senders/Receivers 仍会遇到一些挑战，但与直接操作线程和锁相比，问题相对有限。首先要注意对象寿命与访问这些对象的线程之间的关系。本文特意保留了作者实现时遇到的 BUG，用它强调这一点。手工多线程通常困难得多，因为需要同时推理更多对象，而且许多推理无法局限在当前代码附近。

完成信号的处理也是一道门槛。某些转换会产生意料之外的完成信号，迫使用户显式处理。Sender 连接不当时，编译器可能输出冗长而晦涩的错误。本例就必须把两种错误完成归并成一种类型，才能让流水线正确连接。

这些案例集中体现了 Senders/Receivers 的几项优势：

- **结构化**：Senders/Receivers 为应用程序中的并发建立清晰结构。结构良好的代码会让并发作用域彼此嵌套，外围构造，例如函数或协程，可以隐藏内部的并发细节。框架也支持弱结构化并发，词法作用域不必完全嵌套，但可以用动态作用域包住全部计算。这两种方式都优于用裸线程和锁组织非结构化并发；
- **局部推理**：大多数并发推理可以限制在局部范围。完全结构化的代码中，所有推理都留在局部；弱结构化代码中的并发虽然可能越过当前函数，仍被约束在明确的动态作用域内；
- **安全性**：结构化作用域和显式依赖能减少悬空任务等问题，但不能自动消除数据竞争与死锁。共享状态仍需正确同步，对象寿命也必须覆盖访问它们的异步操作；
- **性能**：Senders/Receivers 的静态组合允许实现消除不必要的抽象开销，但是否分配内存、需要多少同步，仍由具体算法、调度器和实现决定。

这些特性让 Senders/Receivers 成为编写多线程代码的一套优秀框架。它的语法可能不够直观，诊断信息偶尔也更难处理，但它为构建健壮、高效的多线程软件提供了有力工具。

真正的问题是，这套框架在你的代码里表现如何。它是否像本文描述的这样直接，还是在解决实际问题时遇到了别的困难？我很希望听到读者的反馈和使用经验。

## 参考资料

- [ExamplesCode] Lucian Radu Teodorescu, [overload185_sr_examples](https://github.com/lucteo/overload185_sr_examples).
- [OpenCV] [OpenCV: Open Computer Vision Library](https://opencv.org/).
- [P2079R5] Lucian Radu Teodorescu 等，[System execution context](https://wg21.link/P2079R5), 2024.
- [P2300R10] Michał Dominiak 等，[`std::execution`](https://wg21.link/P2300R10), 2024.
- [P3149R6] Ian Petersen 等，[async_scope: Creating scopes for non-sequential concurrency](https://wg21.link/P3149R6).
- [stdexec] NVIDIA, [Senders: A Standard Model for Asynchronous Execution in C++](https://github.com/NVIDIA/stdexec).
- [Teodorescu24] Lucian Radu Teodorescu，[Senders/Receivers: An Introduction](https://accu.org/journals/overload/32/184/teodorescu/)，*Overload* 184，2024 年 12 月。
- [Teodorescu23] Lucian Radu Teodorescu，[Concurrency Approaches: Past, Present, and Future](https://www.youtube.com/watch?v=uSG240pJGPM)，ACCU Conference，2023.
- [WG21Exec] WG21，[Execution control library](https://eel.is/c++draft/#exec)，*Working Draft Programming Languages – C++*.
- [Wikipedia] Wikipedia，[Resource contention](https://en.wikipedia.org/wiki/Resource_contention).
