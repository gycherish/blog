---
media_subpath: /assets/img/notes
author: gycherish
title: "通用异步编程：从零实现 Sender/Receiver"
tags:
  - c++
  - concurrency
  - sender-receiver
  - execution
categories:
date: 2026-07-25
original_author: Eric Niebler
original_url: https://www.youtube.com/watch?v=xiaqNvqRB2E
original_date: 2022-06-29
source_code_url: https://godbolt.org/z/dnrabsbdq
source_slides_url: https://github.com/CppCon/CppCon2021/blob/main/Presentations/Working_with_Asynchrony_Generically_Parts_1_2_Eric_Niebler_1.pptx
---

> 译者说明：本文根据 Eric Niebler 在 CppEurope 2022 的演讲 [《Working with Asynchrony Generally》](https://www.youtube.com/watch?v=xiaqNvqRB2E)重新翻译并整理。原视频是一场现场编码，视频说明只附了 [Compiler Explorer 完整代码](https://godbolt.org/z/dnrabsbdq)，CppEurope 没有发布这场演讲的独立 PPT。Eric 在开场提到，他原本准备沿用此前的 CppCon 演讲，因此本文也参考了 CppCon 2021 官方资料库中的 [《Working with Asynchrony Generically, Parts 1 & 2》幻灯片](https://github.com/CppCon/CppCon2021/blob/main/Presentations/Working_with_Asynchrony_Generically_Parts_1_2_Eric_Niebler_1.pptx)，用来核对开头的设计图和术语。它是相关演讲材料，不是本场视频的逐页配套幻灯片。
>
> 原视频以 2022 年的提案状态为背景，当时目标还是 C++23。此后 [P2300R10](https://wg21.link/P2300R10) 于 2024 年进入 C++26 工作草案，部分接口名称和语义也发生了变化。正文保留演讲的推导过程，在涉及当前标准时另行说明。口语中的重复、现场输入停顿和已经改正的拼写错误没有逐字保留，代码则按最终版本整理，并补上了头文件和一个队列复用修正。本文所有实现都只是教学代码，不能替代标准库实现。

如果只看 Sender/Receiver 的提案文本，很容易先被概念和类型系统淹没。这场演讲换了一种办法：从一个立即产生整数 `42` 的 Sender 开始，一小时内写出 `just`、`then`、`sync_wait`、调度器、事件循环和独立工作线程。代码虽然简化，却足以回答三个关键问题：Sender 怎样描述工作，Receiver 怎样接收完成通知，惰性的计算又怎样真正开始执行。

## 标准异步编程模型要解决什么

执行器提案在委员会里讨论了很多年。它首先要为 C++ 提供一套标准异步编程模型，让库作者可以用共同的方式暴露异步计算。它还要表达工作在何处、以何种方式、何时执行，并允许程序接入自己的计算资源，例如事件循环、线程池、系统执行上下文、GPU、NUMA 节点乃至集群。

这套模型也需要一组通用异步算法。`then` 可以在一项工作之后继续计算，`when_all` 可以并发启动多项工作并等待它们全部完成，`sync_wait` 则在同步代码与异步代码之间建立一道阻塞边界。

Sender/Receiver 里最常遇到的三个概念是：

- **Sender** 表示一个惰性的计算。它描述将来可能产生的结果，但创建 Sender 时通常不会执行工作；
- **Receiver** 是完成处理器，可以把它理解成延续（continuation）或回调。计算完成后，结果不会像普通函数那样返回给调用者，而是交给 Receiver；
- **Scheduler** 是计算资源的句柄。它可能只保存一个线程池指针，也可能指向事件循环或其他执行环境。

这三者形成了一条很简单的组合规则：Scheduler 产生 Sender，异步算法接收 Sender，再返回新的 Sender。复杂计算就这样由较小的计算逐层组合出来。

相关 PPT 用下面的例子说明这种组合。代码先取得线程池的 Scheduler，再创建三条工作链，最后通过 `when_all` 把它们合并：

```cpp
namespace ex = std::execution;

unifex::static_thread_pool pool{8};
ex::scheduler auto sched = pool.get_scheduler();

ex::sender auto work = ex::when_all(
    ex::then(ex::schedule(sched), [] {
        return compute_intensive(0);
    }),
    ex::then(ex::schedule(sched), [] {
        return compute_intensive(1);
    }),
    ex::then(ex::schedule(sched), [] {
        return compute_intensive(2);
    }));

auto [a, b, c] = std::this_thread::sync_wait(std::move(work)).value();
```

这里最重要的一点是惰性。`work` 只是计算描述；如果没有最后的 `sync_wait`，任务不会进入线程池，也不会开始执行。

> 上面是 2021 至 2022 年提案和 libunifex 的示意写法，用于说明演讲语境，不应直接当作当前标准库示例。C++26 工作草案中的接口以 [`[exec]`](https://eel.is/c++draft/exec) 为准。

## 一项异步操作怎样走完生命周期

理解 Sender/Receiver，关键不是记住大量算法，而是看清一项操作从描述到完成要经历什么。

调用 `schedule(scheduler)` 会得到一个 Sender。随后，`connect(sender, receiver)` 把计算描述与完成处理器连接起来，返回一个**操作状态（operation state）**。操作状态保存异步操作执行期间需要存活的全部数据。到这里为止，工作依然没有开始。

只有调用 `start(operation)`，操作才会启动。它可能被放进队列，过一段时间再由某个线程执行。完成时，操作通过以下三条通道之一通知 Receiver：

- `set_value`：成功完成，可以携带零个或多个结果值；
- `set_error`：以错误结束；
- `set_stopped`：收到停止请求，没能产生值或错误。

如果一项操作发出完成通知，它只能选择其中一条通道，并且至多通知一次。用接近代码的形式表示，四个核心接口就是：

```cpp
schedule(scheduler) -> sender
connect(sender, receiver) -> operation_state
start(operation_state)

set_value(receiver, values...)
set_error(receiver, error)
set_stopped(receiver)
```

普通用户主要接触 Scheduler、Sender 和组合算法。Receiver 与操作状态更多出现在异步算法的实现内部。接下来从实现者的角度走一遍，正好能看到它们如何配合。

## 准备几项辅助定义

示例只用 C++20 标准库。为了让后面的代码能够独立编译，先列出所需头文件：

```cpp
#include <condition_variable>
#include <exception>
#include <iostream>
#include <mutex>
#include <optional>
#include <thread>
#include <type_traits>
#include <utility>
```

操作状态的地址在启动后可能被底层执行资源保存，因此不能随意移动。这里定义一个不可移动的基类，并准备两个类型别名：

```cpp
struct immovable {
    immovable() = default;
    immovable(immovable&&) = delete;
};

template <class S, class R>
using connect_result_t =
    decltype(connect(std::declval<S>(), std::declval<R>()));

template <class S>
using sender_result_t = typename S::result_t;
```

`connect_result_t<S, R>` 表示把类型 `S` 的 Sender 与类型 `R` 的 Receiver 连接后得到的操作状态类型。`sender_result_t<S>` 是本例为了简化代码自定义的结果类型查询。真正的 Sender 可以有多组成功结果、不同错误类型和停止完成，C++26 因此使用**完成签名（completion signatures）**描述它们，而不是一个 `result_t`。

## `just`：把普通值变成 Sender

`just(value)` 创建一个立即成功的 Sender。它要保存这个值，连接 Receiver 后再把二者一并放进操作状态：

```cpp
template <class R, class T>
struct just_operation : immovable {
    R rec;
    T value;

    friend void start(just_operation& self) {
        set_value(self.rec, self.value);
    }
};

template <class T>
struct just_sender {
    using result_t = T;
    T value;

    template <class R>
    friend just_operation<R, T> connect(just_sender self, R rec) {
        return {
            {},
            rec,
            self.value
        };
    }
};

template <class T>
just_sender<T> just(T value) {
    return {value};
}
```

`just_sender::connect` 返回 `just_operation`，但没有执行任何工作。直到有人对操作状态调用 `start`，它才调用 `set_value`，把保存的值交给 Receiver。这个 Sender 在 `start` 期间同步完成，仍然符合统一的生命周期。

可以准备一个只负责输出结果的 Receiver 来验证它：

```cpp
struct cout_receiver {
    friend void set_value(cout_receiver, auto value) {
        std::cout << "Result: " << value << '\n';
    }

    friend void set_error(cout_receiver, std::exception_ptr) {
        std::terminate();
    }

    friend void set_stopped(cout_receiver) {
        std::terminate();
    }
};

auto sender = just(42);
auto op = connect(sender, cout_receiver{});
start(op);  // 输出 Result: 42
```

这当然是计算 `42` 最绕的方式，但 Sender、Receiver、操作状态和 `start` 已经全部出现了。

## `then`：在完成通道上接入下一步计算

下一项工作是在已有 Sender 后面连接一个函数。`then(sender, function)` 自己也返回 Sender，因此它还能继续参与组合。

先看 `then_receiver`。它包住下游 Receiver 和变换函数 `f`。上游成功时，它调用 `f(value)`，再把结果交给下游；上游报告错误或停止时，它只把相应信号向后传递：

```cpp
template <class R, class F>
struct then_receiver {
    R rec;
    F f;

    friend void set_value(then_receiver self, auto value) {
        set_value(self.rec, self.f(value));
    }

    friend void set_error(then_receiver self, std::exception_ptr err) {
        set_error(self.rec, err);
    }

    friend void set_stopped(then_receiver self) {
        set_stopped(self.rec);
    }
};
```

`then_operation` 不需要另建启动机制。它保存上游操作状态，自己的 `start` 只负责启动上游：

```cpp
template <class S, class R, class F>
struct then_operation : immovable {
    connect_result_t<S, then_receiver<R, F>> op;

    friend void start(then_operation& self) {
        start(self.op);
    }
};
```

最后由 `then_sender` 保存上游 Sender 和函数。它收到下游 Receiver 后，不是直接把这个 Receiver 交给上游，而是先包成 `then_receiver`。这样，上游的完成信号会先经过变换，再抵达下游：

```cpp
template <class S, class F>
struct then_sender {
    using result_t = std::invoke_result_t<F, sender_result_t<S>>;

    S sender;
    F f;

    template <class R>
    friend then_operation<S, R, F>
    connect(then_sender self, R rec) {
        return {
            {},
            connect(self.sender, then_receiver<R, F>{rec, self.f})
        };
    }
};

template <class S, class F>
then_sender<S, F> then(S sender, F f) {
    return {sender, f};
}
```

现在可以把 `42` 送进 lambda，将结果加一：

```cpp
auto sender = then(just(42), [](int value) {
    return value + 1;
});
auto op = connect(sender, cout_receiver{});
start(op);  // 输出 Result: 43
```

这里有一个值得停下来观察的结构。外层 `then_sender` 在连接时创建 `then_receiver`，再递归连接内层 `just_sender`。操作状态因此层层嵌套，Receiver 也反向嵌套。启动沿着操作状态向内传递，完成信号则从内向外返回，每一层适配器都有机会在启动或完成时加入自己的行为。

演示版 `then_receiver` 没有捕获 `f` 抛出的异常。生产实现必须遵守完成协议，把可传播的异常转换成 `set_error`，同时处理 `void`、多个参数、值类别和多组完成签名。

## `sync_wait`：在同步世界里等待异步结果

异步操作可能在另一个线程完成。`sync_wait` 需要启动 Sender，阻塞当前线程，并在完成通知到来后返回结果。用于在线程间传递状态的控制块包含互斥量、条件变量、异常和完成标志：

```cpp
struct sync_wait_data {
    std::mutex mtx;
    std::condition_variable cv;
    std::exception_ptr err;
    bool done = false;
};
```

配套 Receiver 保存控制块和结果槽的引用。三种完成函数都在持锁状态下更新数据，将 `done` 设为 `true`，然后唤醒等待线程：

```cpp
template <class T>
struct sync_wait_receiver {
    sync_wait_data& data;
    std::optional<T>& value;

    friend void set_value(sync_wait_receiver self, auto value) {
        std::unique_lock lock{self.data.mtx};
        self.value.emplace(value);
        self.data.done = true;
        self.data.cv.notify_one();
    }

    friend void set_error(sync_wait_receiver self, std::exception_ptr err) {
        std::unique_lock lock{self.data.mtx};
        self.data.err = err;
        self.data.done = true;
        self.data.cv.notify_one();
    }

    friend void set_stopped(sync_wait_receiver self) {
        std::unique_lock lock{self.data.mtx};
        self.data.done = true;
        self.data.cv.notify_one();
    }
};
```

`sync_wait` 把输入 Sender 与这个 Receiver 连接起来，启动操作，然后在条件变量上等待。谓词可以处理伪唤醒。操作以错误完成时重新抛出异常，以停止完成时返回空的 `optional`：

```cpp
template <class S>
std::optional<sender_result_t<S>> sync_wait(S sender) {
    using T = sender_result_t<S>;

    sync_wait_data data;
    std::optional<T> value;

    auto op = connect(sender, sync_wait_receiver<T>{data, value});
    start(op);

    std::unique_lock lock{data.mtx};
    data.cv.wait(lock, [&] { return data.done; });

    if (data.err) {
        std::rethrow_exception(data.err);
    }
    return value;
}
```

调用端终于不必亲自处理 Receiver 和操作状态：

```cpp
auto sender = then(just(42), [](int value) {
    return value + 1;
});

int value = sync_wait(sender).value();
std::cout << "Result: " << value << '\n';
```

`sync_wait` 是 Sender 的消费者，也是异步世界的边界工具。它很适合放在 `main`、测试代码或同步 API 的边缘；如果在负责推进异步任务的执行线程中随意阻塞，就可能造成线程饥饿甚至死锁。

## `run_loop`：让工作进入队列

到目前为止，所有操作都在调用 `start` 的线程上立即完成。为了真正改变执行位置，需要一个执行上下文。这里实现一个 `run_loop`，把它看成多生产者、单消费者的先进先出队列。

直接用 `std::vector` 保存任务可能发生动态内存分配。Sender/Receiver 的操作状态本来就要存活到操作完成，因此可以让操作状态自己携带链表节点，组成侵入式队列。

`task` 是队列节点。`head` 是哨兵节点，空队列时指向自己：

```cpp
struct run_loop : immovable {
    struct none {};

    struct task : immovable {
        task* next = this;
        virtual void execute() {}
    };

    // ...
};
```

排入队列的具体对象仍然是操作状态。它继承 `task`，保存 Receiver 和所属的 `run_loop`。`start` 只把自己放进队列；消费者稍后调用 `execute`，操作才通过成功通道完成：

```cpp
template <class R>
struct operation : task {
    R rec;
    run_loop& loop;

    operation(R rec, run_loop& loop)
        : rec(rec), loop(loop) {}

    void execute() override final {
        set_value(rec, none{});
    }

    friend void start(operation& self) {
        self.loop.push_back(&self);
    }
};
```

队列本身保存头尾指针、结束标志、互斥量和条件变量：

```cpp
task head;
task* tail = &head;
bool finishing = false;
std::mutex mtx;
std::condition_variable cv;
```

生产者通过 `push_back` 入队。消费者在 `pop_front` 中等待，直到队列出现任务或事件循环准备结束：

```cpp
void push_back(task* op) {
    std::unique_lock lock{mtx};
    op->next = &head;
    tail = tail->next = op;
    cv.notify_one();
}

task* pop_front() {
    std::unique_lock lock{mtx};
    cv.wait(lock, [this] {
        return head.next != &head || finishing;
    });

    if (head.next == &head) {
        return nullptr;
    }

    task* op = head.next;
    head.next = op->next;
    if (tail == op) {
        tail = &head;
    }
    return op;
}
```

这里补了一处现场代码没有处理的边界：弹出最后一个节点时必须把 `tail` 重置为 `&head`。原代码在演讲的一次性测试中能够得到正确结果，但队列变空后再次入队会继续使用已经弹出的尾指针，不适合复用。

事件循环还要对外提供 Scheduler。`schedule(scheduler)` 返回一个指向当前循环的 Sender，这个 Sender 在连接时创建刚才定义的 `operation`：

```cpp
struct sender {
    using result_t = none;
    run_loop* loop;

    template <class R>
    friend operation<R> connect(sender self, R rec) {
        return {rec, *self.loop};
    }
};

struct scheduler {
    run_loop* loop;

    friend sender schedule(scheduler self) {
        return {self.loop};
    }
};

scheduler get_scheduler() {
    return {this};
}
```

`run` 不断取出任务并执行。`finish` 设置结束标志并唤醒可能正在等待的消费者。队列里已有的任务仍会先执行完，队列为空后 `pop_front` 才返回空指针：

```cpp
void run() {
    while (auto* op = pop_front()) {
        op->execute();
    }
}

void finish() {
    std::unique_lock lock{mtx};
    finishing = true;
    cv.notify_all();
}
```

把这些成员放回 `run_loop`，就得到一个最小执行上下文。可以先向它提交多项工作，再在当前线程运行循环：

```cpp
run_loop loop;
auto sched = loop.get_scheduler();

auto s1 = then(schedule(sched), [](auto) { return 42; });
auto op1 = connect(s1, cout_receiver{});
start(op1);

auto s2 = then(schedule(sched), [](auto) { return 43; });
auto op2 = connect(s2, cout_receiver{});
start(op2);

loop.finish();
loop.run();
```

两次 `start` 只是把操作放进队列。真正的计算发生在 `loop.run()` 所在线程。

## `thread_context`：把事件循环放到工作线程

最后再把 `run_loop` 包进一个独立线程。`thread_context` 继承 `run_loop`，构造时启动工作线程，并公开 Scheduler、结束和等待接口：

```cpp
class thread_context : run_loop {
    std::thread worker{[this] { run(); }};

public:
    using run_loop::finish;
    using run_loop::get_scheduler;

    void join() {
        worker.join();
    }
};
```

现在，调用端只看得到 Scheduler 和 Sender。`schedule` 产生一项将在工作线程完成的空工作，两个 `then` 依次生成 `42` 和 `43`，`sync_wait` 在主线程等待最终结果：

```cpp
int main() {
    thread_context context;
    auto sched = context.get_scheduler();

    auto s1 = then(schedule(sched), [](auto) {
        return 42;
    });
    auto s2 = then(s1, [](int value) {
        return value + 1;
    });

    int result = sync_wait(s2).value();

    context.finish();
    context.join();

    std::cout << result << '\n';
}
```

程序输出：

```text
43
```

`schedule(sched)` 的操作由工作线程执行，它调用 `set_value` 后，嵌套的两个 `then_receiver` 也在同一线程继续运行。最终的 `sync_wait_receiver` 写入结果并唤醒主线程。这段执行路径把整套模型串了起来：

```text
Scheduler
  -> schedule 得到 Sender
  -> then 组合出新的 Sender
  -> connect 构造嵌套的操作状态
  -> start 把操作排入 run_loop
  -> 工作线程 execute
  -> set_value 沿嵌套 Receiver 向外传播
  -> sync_wait 返回 43
```

## 这份教学实现省略了什么

演讲的目标是展示部件怎样咬合，不是重写 P2300。把这份两百行左右的代码用于生产会立刻遇到一系列问题。

首先，真实 Sender 不只有一个 `result_t`。成功完成可以不带值，也可以带多个值，还可能存在多组值类型；错误类型也不局限于 `std::exception_ptr`。C++26 用完成签名完整描述这些可能性。

其次，真正的 `then` 要处理函数返回 `void`、移动语义、约束检查和异常转换。Receiver 还带有环境（environment），算法可从环境中查询停止令牌、Scheduler 和其他属性。

停止也不只是调用 `set_stopped`。它通常包含停止请求如何从外层传播到子操作、异步源如何注册回调，以及停止请求与正常完成并发发生时如何仲裁。相关 PPT 的后半部分专门用 `stop_when` 和键盘事件说明了这些问题，本场现场编码没有实现它们。

最后，执行上下文需要严谨的关闭协议、析构行为、异常安全和并发测试。这里的 `thread_context` 要求调用者显式执行 `finish()` 和 `join()`；如果工作线程仍可连接，直接析构 `std::thread` 会终止进程。

因此，“一小时写出 Sender/Receiver”证明的是核心控制流并不神秘，不代表一套符合标准、覆盖边界条件的实现也同样简单。

## 2022 年演讲与 C++26 的差异

视频说明和相关 PPT 都把执行器写成面向 C++23 的工作，当时完成停止通知还常写作 `set_done`。后来提案继续演化，[P2300R10](https://wg21.link/P2300R10) 以 `std::execution` 为基础进入 C++26 工作草案，停止完成名称定为 `set_stopped`。

当前标准模型仍保留了演讲中的骨架：

- Sender 描述异步计算及其完成方式；
- `connect` 将 Sender 与 Receiver 绑定，生成操作状态；
- `start` 启动操作状态；
- Receiver 通过 `set_value`、`set_error`、`set_stopped` 三类完成操作接收结果；
- Scheduler 的 `schedule` 返回 Sender，算法继续接收和返回 Sender。

变化主要发生在完整类型系统、环境查询、停止协议、算法集合和定制规则上。学习这份实现时，可以把它当作控制流示意图；编写 C++26 代码时，仍应以工作草案和所用实现的文档为准。

## 问答：Ranges、库设计与异步抽象

现场编码结束后，问答转向了 Eric 的 Ranges 工作、库设计经验，以及 Sender/Receiver 可以覆盖的场景。下面保留其中与主题有关的主要内容。

### Range-v3 是怎样开始的

Ranges 的历史可以追溯到 Boost.Range。早期版本主要提供自由函数 `begin`、`end`，以及接收 Range 后转调标准算法的包装。Eric 认为 Range 还能带来组合能力：如果把 Boost.Iterator 中的 transform iterator、filter iterator 一类适配器与 Boost.Range 放在一起，就可以构建管道。

他先做了一个概念验证，在 Boost 社区里得到不少关注，但当时觉得设计还不成熟，没有继续提交。Boost.Range 的作者 Thorsten Ottosen 接过这项思路，把可用管道组合的 Range 适配器放进后来称为 Boost.Range 2 的版本。

再后来，Concepts 看起来真的会进入语言。给现有 STL 反向补上 Concepts 很困难，重新设计一套算法和 Range 接口反而更合适。Eric 因此开始编写 range-v3。这个名字原本表示“Boost.Range 的第三版”，但 C++17 的时间窗口很紧，他没有先走 Boost 流程，而是直接在 GitHub 发布并提交标准提案。它后来成为 Ranges TS，并最终进入 C++20 的 `std::ranges`。整个过程前后大约用了五年。

### 设计库时最难的是什么

最难的部分是弄清楚自己究竟在构建什么。人们很容易以为自己已经理解问题领域，也知道解法应该是什么样子，实际往往并非如此。

Eric 的做法是先写原型，用它解决一些实际问题，观察自己和其他人怎样使用，再判断抽象是否抓住了真正的问题。有些项目做完一个版本后，他才发现解决的是错误问题，只能全部丢掉重来。类似过程可能重复三四次，直到对领域有足够理解。这里没有捷径，只能逐步试验。

### 如果能回到 C++11，他会怎样改并发库

Eric 希望 C++11 引入线程时，就能同时提供 Sender/Receiver 或协程一类结构化抽象。C++11 为线程、内存模型和原子操作做了大量语言与基础库工作，但留给上层并发接口的设计并不充分。

他对当时接口的批评很直接：`std::future` 缺少组合能力，通常只能阻塞等待；`std::async` 的执行策略不够直观，返回的 Future 仍然难以继续组合；互斥量、条件变量和锁虽然必要，却不适合作为每个应用直接组织异步业务的主要接口。显式创建线程、共享状态并到处加锁会形成非结构化并发，难以局部推理，也容易出现死锁和生命周期问题。

协程已经向前迈了一大步。它让异步控制流重新获得类似普通函数的结构，代码可以在需要暂停的位置使用 `co_await`。Sender/Receiver 则为不同异步来源和通用算法提供统一协议，两者可以配合，而不是互相替代。

### `std::ranges` 最缺哪些 range-v3 功能

2022 年回答这个问题时，Eric 提到了 `repeat`、`cartesian_product` 和 `concat` 等适配器。当时其中一些已经进入 C++23 的推进过程，Ranges 的后续工作也不再只由他推动。委员会里已经有一批成员继续从 range-v3 中整理功能、推进标准化，而他的主要精力转向了异步编程。

这段回答有明确的时间背景。哪些 View 已经进入后续标准，应以对应版本的标准库文档为准，不能把 2022 年的“尚未提供”直接当成今天的结论。

### Sender 能否包装 RPC 或点对点网络操作

可以。只要异步 API 能注册完成处理，就能在它外面封装一个 Sender。这样，RPC、点对点网络或其他 I/O 操作便可以交给同一组通用异步算法处理，例如组合后续工作、设置超时或与其他操作汇合。

不过 Sender 只统一完成协议，并不会自动解决网络层的重试、幂等、背压、分布式取消或故障恢复。这些语义仍要由具体 API 定义。

### Sender 与响应式编程有什么关系

演讲中给出的直觉是，一组 Sender 可以看成一种简单的响应式流。Sender 可以与协程集成，因此代码可以在循环中逐项 `co_await`，等待下一个元素到来。要把这个想法扩展成完整的异步流，还需要异步 Range 适配器、背压和取消等机制。相关 PPT 将它列为后续探索方向，而不是当时 P2300 已经提供的完整能力。

## 结语

这场现场编码最有价值的地方，是把 Sender/Receiver 从一组抽象名词还原成一条可跟踪的调用链。Sender 保存计算描述，`connect` 把描述与完成处理器编译成操作状态，`start` 负责启动，三种完成函数把结果沿 Receiver 链送回去。Scheduler 只需从执行资源产生 Sender，`then` 一类算法就能在不认识具体线程池或事件循环的情况下继续组合工作。

教学实现离标准库还有很远，但核心结构已经完整出现。以后再看 `when_all`、停止传播、协程互操作或结构化并发时，它们不再是另一套概念，而是在同一生命周期上增加新的组合与约束。

## 资料

- Eric Niebler，[Working with Asynchrony Generally and AMA at CppEurope 2022](https://www.youtube.com/watch?v=xiaqNvqRB2E)，CppEurope，2022-06-29。
- Eric Niebler，[CppEurope 2022 现场代码](https://godbolt.org/z/dnrabsbdq)。
- Eric Niebler，[Working with Asynchrony Generically, Parts 1 & 2](https://github.com/CppCon/CppCon2021/blob/main/Presentations/Working_with_Asynchrony_Generically_Parts_1_2_Eric_Niebler_1.pptx)，CppCon 2021 幻灯片。
- Michał Dominiak、Georgy Evtushenko、Lewis Baker、Lucian Radu Grijincu、Kirk Shoop、Eric Niebler，[P2300R10: `std::execution`](https://wg21.link/P2300R10)。
- [C++ 工作草案：Execution control library](https://eel.is/c++draft/exec)。
