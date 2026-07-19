---
media_subpath: /assets/img/notes
author: gycherish
title: 眼见不一定为实：C++ 可见性与 happens-before
tags:
  - c++
  - concurrency
  - synchronizes-with
  - happens-before

categories:
date: 2026-07-19 21:00
---

## 从一段错误代码说起

先看这段多线程代码：

```cpp
int data = 0;
bool ready = false;

// 生产者线程
data = 42;
ready = true;

// 消费者线程
while (!ready) {}
std::cout << data << "\n";
```

意图很直白：生产者先把 `data` 写好，再把 `ready` 置为 `true`；消费者等 `ready` 变为 `true` 后，就去读 `data`。

它一定会打印 `42` 吗？`while (!ready) {}` 一定会结束吗？

两个问题的答案都是"不一定"。这段代码看着在考多线程同步，真正问的是一件更基本的事：一个线程写下的值，另一个线程什么时候才保证看得见。

上一篇 [i = i++ 到底等于几：C++ 副作用与求值顺序](/blog/posts/i-=-i++-到底等于几-C++-副作用与求值顺序/) 在单线程里讲清了求值顺序问题，这一篇讲多线程里的可见性问题。

## 单线程为什么不出问题

先回到单线程。上一篇讲过，在一个线程内部，抽象机按源码顺序求值，标准用 `sequenced-before` 描述这种线程内的先后顺序。再加上 `as-if` 规则的作用，即使编译器和 CPU 调换、合并、删除中间步骤，程序的可观察行为也会和抽象机一致。

所以在单线程里，"先写 `data` 再写 `ready`，并且当后续读到 `ready` 为 `true` 时，`data` 一定是 `42`。但是这套规则只在单线程内有效。

## 多线程为什么出问题

再看生产者的代码：

```cpp
data = 42;      // (1)
ready = true;   // (2)
```

在生产者自己看来，(1) `sequenced-before` (2)。但这只是**线程内**的顺序。站在消费者的视角，当它看到 `ready` 变真，(1) 的写是否已经可见，标准不作保证。常见原因有两层：

- **编译器优化**：(1) 和 (2) 写的是两个无关变量，`as-if` 规则下编译器可以先生成 (2)、再生成 (1)。
- **CPU 执行**：就算指令顺序不变，现代 CPU 有存储缓冲（store buffer）、乱序执行、多级缓存。一个线程依次写出的两个值，另一个线程可能以相反的顺序看到。

于是消费者可能看到 `ready` 为真、`data` 仍可能是 `0`。它甚至可能因为编译器把 `!ready` 的读提到循环外而陷进死循环。

有人会想到给 `ready` 加 `volatile`，但它仍然解决不了问题。`volatile` 保证的是对这个变量的访问不被优化掉，它最早是为内存映射 I/O 和硬件寄存器设计的，[标准](https://eel.is/c++draft/intro.execution#7)把访问 `volatile` 对象列为一种副作用，但它从不承诺跨线程的顺序或可见性。`volatile bool` 和普通 `bool` 一样中招。

## 什么是可见性

那么，到底什么是可见性？简单来说，可见性描述的是一个线程对某个对象的写，何时以及能不能被另一个线程读到的问题。

上文中说消费者可能读到值为 0 的 `data`。实际情况可能更糟糕，因为生产者线程和消费者线程在没有同步的情况下并发访问同一个变量，并且其中一个是写，这种场景在标准中有一个更精确的名字，即**[数据竞争（data race）](https://eel.is/c++draft/intro.races#17.sentence-2)**，其后果是未定义行为：

> *The execution of a program contains a data race if it contains two potentially concurrent conflicting actions, at least one of which is not atomic, and neither happens before the other [...] Any such data race results in undefined behavior.*

那么，如何让生产者线程对 `data` 的写对消费者可见呢？我们先看下标准草案对可见性的描述：

> *A visible side effect A on a scalar object or bit-field M with respect to a value computation B of M satisfies the conditions: A happens before B and there is no other side effect X on M such that A happens before X and X happens before B. [...] The value of a non-atomic scalar object or bit-field M, as determined by evaluation B, is the value stored by the visible side effect A.*

翻译过来就是：写操作 A 对变量 M 的修改，要对读操作 B 可见，前提是 A `happens-before` B；并且 A 与 B 之间不能再夹着另一个对 M 的写操作 X，使 A `happens-before` X 且 X `happens-before` B，因为这会导致 B 读到的是 X 写入的值。

因此，为了让生产者线程对 `data` 的写对消费者线程可见，必须让 `data = 42` `happens-before` `std::cout << data << "\n"`。

## happens-before

`happens-before` 是 C++ 内存模型中最核心的概念之一。它定义了多线程程序中操作之间的顺序和可见性关系，是判断是否存在数据竞争、保证程序正确运行的理论基础。

标准草案对 [happens-before](https://eel.is/c++draft/intro.races#7) 的定义是：

> *An evaluation A happens before an evaluation B (or, equivalently, B happens after A) if either A is sequenced before B, or A synchronizes with B, or A happens before X and X happens before B.*

这条定义揭示了 `happens-before` 的构建路径：
- 线程内：sequenced-before 关系自然蕴含 happens-before。
- 线程间：synchronizes-with 关系建立了跨线程的 happens-before。
- 传递性：若 A happens-before X，且 X happens-before B，则 A happens-before B。

根据上文对数据竞争的描述可以看出，`happens-before` 关系还能够解决数据竞争问题。

上一篇已经讲过 `sequenced-before` 关系，因此，要想建立跨线程的 `happens-before` 关系，只要理解哪些操作会形成 `synchronizes-with` 关系即可。

## synchronizes-with

常见的能够建立 `synchronizes-with` 关系的设施有以下几种。

### mutex

[互斥锁](https://eel.is/c++draft/thread.mutex.requirements) 是最经典的同步方式：一个线程对互斥量的解锁 (unlock) 操作，会与另一个线程随后对同一个互斥量的加锁 (lock) 操作形成 `synchronizes-with` 关系。

```cpp
std::mutex mtx;
int shared_data = 0;

// 线程 1 
{
    std::lock_guard<std::mutex> lock(mtx);
    shared_data = 42;
} // 解锁操作 A

// 线程 2 
{
    std::lock_guard<std::mutex> lock(mtx); // 加锁操作 B
    int val = shared_data;
}
```

这里当 A 先完成时，A `synchronizes-with` B，因此 A 的写对 B 可见。

考虑到互斥锁使用简单、不容易犯错，大多数业务代码应当首选互斥锁用于线程同步。

### thread

[线程构造完成](https://eel.is/c++draft/thread.thread.constr#6)  `synchronizes-with` 新线程函数开始执行，所以新线程创建时线程函数看得到线程启动前准备的状态。这也是为何我们新建线程时可以放心读取外部变量的原因。

[线程函数完成](https://eel.is/c++draft/thread.thread.member#4) `synchronizes-with` `join()` 成功返回。这也是为何等待线程结束后，我们可以放心读取被子线程修改的变量的原因。

```cpp
int input = 1; // 线程启动前的写操作 A
int output = 0; 

std::thread t([&] {
    int in = input; // 线程函数内的读操作 B
    output = in + 1; // 线程函数内的写操作 C
});

t.join(); // join 成功返回 D
std::cout << output << "\n";
```

这里 A `synchronizes-with` B，所以 A 的写对 B 可见。C `synchronizes-with` D，所以 C 的写对 D 可见。因此，程序最终输出 `2`。

### call_once

同一个 [once_flag](https://eel.is/c++draft/thread.once.callonce#3) 上，真正执行初始化函数的那次调用 `synchronizes-with` 后续返回的 `call_once`。

```cpp
std::once_flag flag;
std::string config;

void init() {
    std::call_once(flag, [] {
        config = load_config();
    });

    use(config);
}
```

当 `std::call_once` 真正被调用时，config 的修改结果对后续所有调用 `init()` 的线程可见。

### future/promise

把结果写入[共享状态](https://eel.is/c++draft/futures.state#9) `synchronizes-with` 等待 `future.get()` 函数成功返回。`std::async`、`packaged_task` 背后是同一套共享状态语义。

```cpp
std::promise<int> p;
std::future<int> f = p.get_future();

std::thread t([&] {
    p.set_value(42); // 写入共享状态操作 A
});

int value = f.get(); // 读取共享状态操作 B
t.join();
```

其中 A `synchronizes-with` B，所以 A 的写对 B 可见。

### atomic

[原子操作](https://eel.is/c++draft/atomics.order#2) 的 release 操作 `synchronizes-with` 其对应的 acquire 操作。

这里使用原子变量修复上文中的例子：

```cpp
int data = 0;
std::atomic<bool> ready = false;

// 生产者线程
data = 42; // 写入数据操作 A
ready.store(true, std::memory_order_release); // 原子写入操作 B

// 消费者线程
while (!ready.load(std::memory_order_acquire)) {} // 原子读取操作 C
std::cout << data << "\n"; // 数据读取操作 D
```

这里 A `sequenced-before` B，当 C 读到 true 时，B `synchronizes-with` C，C `sequenced-before` D，最终 A `happens-before` D。因此，程序最终输出 `42`。
