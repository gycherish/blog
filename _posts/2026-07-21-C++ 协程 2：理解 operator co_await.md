---
media_subpath: /assets/img/notes
author: gycherish
title: "C++ 协程 2：理解 operator co_await"
tags:
  - c++
  - coroutine
categories:
date: 2026-07-21
original_author: Lewis Baker
original_url: https://lewissbaker.github.io/2017/11/17/understanding-operator-co-await
original_date: 2017-11-17
---

> 译者说明：本文是 Lewis Baker 的文章《理解 operator co_await》的非官方中文翻译，[英文原文](https://lewissbaker.github.io/2017/11/17/understanding-operator-co-await)发表于 2017 年 11 月 17 日。文中的标准状态和技术背景以原文发表时间为准；代码保持原样，系列内链接改为本站译稿。

上一篇 [协程理论](/blog/posts/C++-协程-1-协程理论/) 从较高层次比较了函数与协程，但没有深入 C++ 协程 TS（[N4680](http://www.open-std.org/jtc1/sc22/wg21/docs/papers/2017/n4680.pdf)）规定的语法和语义。

协程 TS 为 C++ 增加的关键能力，是让协程可以挂起，稍后再恢复。实现这项能力的核心机制就是新的 `co_await` 运算符。

理解 `co_await` 的工作方式，协程如何挂起和恢复就不再神秘。本文会解释 `co_await` 的具体机制，并引入两个相关的类型概念：**Awaitable（可等待对象）**和 **Awaiter（等待器）**。

不过在深入 `co_await` 之前，先简单了解下协程 TS 提供了什么。

## 协程 TS 提供了什么

* 三个新语言关键字：`co_await`、`co_yield` 和 `co_return`
* `std::experimental` 命名空间中的几个新类型：
  * `coroutine_handle<P>`
  * `coroutine_traits<Ts...>`
  * `suspend_always`
  * `suspend_never`
* 一套供库作者与协程交互、定制协程行为的通用机制；
* 一组能显著简化异步代码的语言设施。

C++ 协程 TS 提供的语言设施可以看成协程领域的*低级汇编语言*。直接安全地使用它们并不容易，主要受众是库作者。库作者在这些低层构件之上封装高层抽象，应用开发者再使用封装后的类型。

写作本文时，计划是把这些低层设施纳入即将到来的语言标准，希望会是 C++20；标准库也将配套提供若干高层类型，封装底层构件，让应用开发者更容易安全地使用协程。

## 编译器与库如何交互

协程 TS 并没有直接规定某一种协程语义。它不决定调用协程时如何产生返回对象，不决定怎样处理传给 `co_return` 的值或逃出协程的异常，也不决定协程应该在哪个线程上恢复。

它规定的是一套通用的定制机制。库代码实现满足特定接口的类型，编译器再生成代码，调用这些类型实例上的方法。这个思路与定制范围 `for` 循环相似：库作者通过定义 `begin()`、`end()` 和 `iterator` 类型决定循环的行为。

正因为没有写死具体语义，同一套机制才能支撑用途完全不同的协程类型。

例如，可以定义异步产生单个值的协程，也可以定义惰性产生一系列值的协程；还可以定义一种协程，在遇到 `nullopt` 时提前退出，从而简化处理 `optional<T>` 的控制流。

协程 TS 定义了两套接口：**Promise** 和 **Awaitable**。

**Promise** 接口负责定制协程本身。库作者可以决定协程被调用时发生什么，协程正常返回或因未处理异常退出时发生什么，还可以定制协程体内每个 `co_await` 和 `co_yield` 表达式的行为。

**Awaitable** 接口负责控制 `co_await` 表达式的语义。对一个值执行 `co_await` 时，编译器会把表达式转换成一组方法调用。被等待对象可以借此决定是否挂起当前协程，在挂起后如何安排它恢复，以及协程恢复后如何产生 `co_await` 表达式的结果。

**Promise** 接口留到后续文章再讲，这里先看 **Awaitable**。

## Awaitable 与 Awaiter：`operator co_await` 的工作方式

`co_await` 是一个作用于值的一元运算符，例如 `co_await someValue`。

`co_await` 只能出现在协程上下文中。这句话多少有些同义反复，因为只要函数体包含 `co_await`，这个函数按定义就会被编译成协程。

支持 `co_await` 的类型称为 **Awaitable** 类型。

一种类型能否被 `co_await`，可能取决于表达式所处的协程上下文。协程的 Promise 类型可以通过 `await_transform` 方法改变协程体内 `co_await` 的含义，后文会详细说明。

说得更具体些，如果一个类型在 Promise 类型不含 `await_transform` 成员时也支持 `co_await`，我称它为 **Normally Awaitable（通常可等待）**。如果它依靠某类协程的 Promise 所提供的 `await_transform`，只在特定协程上下文中支持 `co_await`，我称它为 **Contextually Awaitable（上下文可等待）**。这两个名字未必完美，欢迎提出更好的叫法。

**Awaiter** 类型实现三个特殊方法：`await_ready`、`await_suspend` 和 `await_resume`。编译器在展开 `co_await` 表达式时会调用它们。

“Awaiter”这个名字是我从 C# `async` 机制中借来的。C# 的 `GetAwaiter()` 方法会返回一个对象，其接口与 C++ 的 **Awaiter** 概念非常相似。想了解 C# Awaiter 的细节，可以参阅[这篇文章](https://weblogs.asp.net/dixin/understanding-c-sharp-async-await-2-awaitable-awaiter-pattern)。

同一个类型可以既是 **Awaitable**，又是 **Awaiter**。

编译器看到 `co_await <expr>` 后，具体采用哪种转换取决于参与其中的类型。

### 获取 Awaiter

编译器首先生成代码，为被等待的值获取 **Awaiter** 对象。具体步骤列在 N4680 的 5.3.8(3) 节中。

假设当前协程的 Promise 对象类型为 `P`，`promise` 是指向该对象的左值引用。

如果 Promise 类型 `P` 含有名为 `await_transform` 的成员，编译器先调用 `promise.await_transform(<expr>)`，把结果作为 **Awaitable** 值 `awaitable`。如果没有这个成员，就直接把 `<expr>` 的求值结果作为 `awaitable`。

接着，如果 **Awaitable** 对象 `awaitable` 存在可用的 `operator co_await()` 重载，编译器就调用它来获取 **Awaiter**；否则直接把 `awaitable` 本身当作 **Awaiter**。

把这些规则写成 `get_awaitable()` 和 `get_awaiter()`，大致如下：
```c++
template<typename P, typename T>
decltype(auto) get_awaitable(P& promise, T&& expr)
{
  if constexpr (has_any_await_transform_member_v<P>)
    return promise.await_transform(static_cast<T&&>(expr));
  else
    return static_cast<T&&>(expr);
}

template<typename Awaitable>
decltype(auto) get_awaiter(Awaitable&& awaitable)
{
  if constexpr (has_member_operator_co_await_v<Awaitable>)
    return static_cast<Awaitable&&>(awaitable).operator co_await();
  else if constexpr (has_non_member_operator_co_await_v<Awaitable&&>)
    return operator co_await(static_cast<Awaitable&&>(awaitable));
  else
    return static_cast<Awaitable&&>(awaitable);
}
```

### 等待 Awaiter

有了上面两个辅助函数，`co_await <expr>` 的语义大致可以展开为：
```c++
{
  auto&& value = <expr>;
  auto&& awaitable = get_awaitable(promise, static_cast<decltype(value)>(value));
  auto&& awaiter = get_awaiter(static_cast<decltype(awaitable)>(awaitable));
  if (!awaiter.await_ready())
  {
    using handle_t = std::experimental::coroutine_handle<P>;

    using await_suspend_result_t =
      decltype(awaiter.await_suspend(handle_t::from_promise(promise)));

    <suspend-coroutine>

    if constexpr (std::is_void_v<await_suspend_result_t>)
    {
      awaiter.await_suspend(handle_t::from_promise(promise));
      <return-to-caller-or-resumer>
    }
    else
    {
      static_assert(
         std::is_same_v<await_suspend_result_t, bool>,
         "await_suspend() must return 'void' or 'bool'.");

      if (awaiter.await_suspend(handle_t::from_promise(promise)))
      {
        <return-to-caller-or-resumer>
      }
    }

    <resume-point>
  }

  return awaiter.await_resume();
}
```

`await_suspend()` 的 `void` 返回版本会无条件把控制权交还给协程的调用方或恢复方；`bool` 返回版本则让 Awaiter 决定是否立即恢复协程，而不必先返回调用方或恢复方。

返回 `bool` 的 `await_suspend()` 在 Awaiter 启动的异步操作同步完成时很有用。操作同步完成时，它可以返回 `false`，表示协程应该立即继续执行。

在 `<suspend-coroutine>` 处，编译器生成代码保存协程的当前状态，为以后恢复做准备。其中包括记录 `<resume-point>` 的位置，以及把需要保留的寄存器值溢出到协程帧中。

`<suspend-coroutine>` 完成后，当前协程就处于“已挂起”状态。外部第一次能够观察到这一状态，是调用 `await_suspend()` 的时候。此后，协程可以被恢复，也可以被销毁。

`await_suspend()` 负责安排协程在操作完成后恢复，也可以安排它被销毁。返回 `false` 也算一种安排：协程会在当前线程上立即恢复。

如果事先知道操作会同步完成、无需挂起，`await_ready()` 可以避开 `<suspend-coroutine>` 的成本。

到达 `<return-to-caller-or-resumer>` 后，控制权回到调用方或恢复方，本地栈帧弹出，协程帧仍然存活。

如果已挂起的协程后来恢复，执行会从 `<resume-point>` 继续，也就是调用 `await_resume()` 取得操作结果之前的位置。

`await_resume()` 的返回值就是 `co_await` 表达式的结果。它也可以抛出异常，异常会从 `co_await` 表达式继续向外传播。

如果 `await_suspend()` 抛出异常，协程会自动恢复，异常从 `co_await` 表达式向外传播，且不会调用 `await_resume()`。

## 协程句柄

前面的 `co_await` 展开代码把一个 `coroutine_handle<P>` 传给了 `await_suspend()`。

这个类型是协程帧的非拥有句柄，可以用来恢复协程、销毁协程帧，也可以访问协程的 Promise 对象。

`coroutine_handle` 的接口简化后如下：
```c++
namespace std::experimental
{
  template<typename Promise>
  struct coroutine_handle;

  template<>
  struct coroutine_handle<void>
  {
    bool done() const;

    void resume();
    void destroy();

    void* address() const;
    static coroutine_handle from_address(void* address);
  };

  template<typename Promise>
  struct coroutine_handle : coroutine_handle<void>
  {
    Promise& promise() const;
    static coroutine_handle from_promise(Promise& promise);

    static coroutine_handle from_address(void* address);
  };
}
```

实现 **Awaitable** 类型时，`coroutine_handle` 上最常用的方法是 `.resume()`。操作完成、需要恢复等待中的协程时，就调用它。`.resume()` 会重新激活挂起在 `<resume-point>` 的协程；协程下次到达 `<return-to-caller-or-resumer>` 时，这次 `.resume()` 调用返回。

`.destroy()` 会销毁协程帧：调用仍在作用域内对象的析构函数，并释放协程帧占用的内存。除非你正在实现协程的 Promise 类型，否则通常不需要，也应该避免直接调用它。协程调用一般会返回某种拥有协程帧的 RAII 类型；绕过这个 RAII 对象调用 `.destroy()`，可能造成重复销毁。

`.promise()` 返回协程 Promise 对象的引用。它和 `.destroy()` 一样，主要在实现协程 Promise 类型时才有用。Promise 对象应当视为协程的内部实现细节。大多数 **Normally Awaitable** 类型都应该让 `await_suspend()` 接收 `coroutine_handle<void>`，而非 `coroutine_handle<Promise>`。

`coroutine_handle<P>::from_promise(P& promise)` 可以从 Promise 对象的引用重建协程句柄。类型 `P` 必须与协程帧实际使用的具体 Promise 类型完全一致。实际类型为 `Derived` 时构造 `coroutine_handle<Base>`，可能产生未定义行为。

`.address()/from_address()` 用于在协程句柄与 `void*` 指针之间转换，主要用途是把句柄作为“context”参数传给现有的 C 风格 API。实现某些 **Awaitable** 类型时会用到它。不过实践中，回调往往还需要其他信息，所以我通常把 `coroutine_handle` 存进一个结构体，再把结构体指针作为“context”传入，而不是直接使用 `.address()` 的返回值。

## 无需同步的异步代码

`co_await` 有一项很重要的设计：协程进入已挂起状态之后、控制权返回调用方或恢复方之前，还能执行代码。

Awaiter 因此可以等协程挂起后再启动异步操作，并把已挂起协程的 `coroutine_handle` 交给该操作。操作完成时，即使是在另一个线程上，也可以安全地恢复协程，无需额外同步。

例如，在 `await_suspend()` 中启动异步读取时，协程已经挂起。读取完成后可以直接恢复它，不必用线程同步去协调启动操作的线程和完成操作的线程。


```
Time     Thread 1                           Thread 2
  |      --------                           --------
  |      ....                               Call OS - Wait for I/O event
  |      Call await_ready()                    |
  |      <supend-point>                        |
  |      Call await_suspend(handle)            |
  |        Store handle in operation           |
  V        Start AsyncFileRead ---+            V
                                  +----->   <AsyncFileRead Completion Event>
                                            Load coroutine_handle from operation
                                            Call handle.resume()
                                              <resume-point>
                                              Call to await_resume()
                                              execution continues....
           Call to AsyncFileRead returns
         Call to await_suspend() returns
         <return-to-caller/resumer>
```

这里有一个必须小心的并发问题。一旦把协程句柄发布给可能在其他线程完成的操作，另一个线程就可能在 `await_suspend()` 返回前恢复协程。恢复后的协程会与尚未结束的 `await_suspend()` 并发执行。

协程恢复后首先调用 `await_resume()` 取得结果，随后通常立即销毁 **Awaiter** 对象，也就是 `await_suspend()` 中 `this` 指向的对象。协程甚至可能一路运行结束，在 `await_suspend()` 返回前连协程帧和 Promise 对象也一起销毁。

因此，在 `await_suspend()` 中，一旦协程可能从另一线程并发恢复，就不能再访问 `this` 或协程的 `.promise()` 对象，因为它们可能已经销毁。一般而言，异步操作启动并安排好协程恢复后，剩下还能安全访问的只有 `await_suspend()` 自己的局部变量。

### 与有栈协程比较

这里稍作展开，把协程 TS 的无栈协程与常见的有栈协程设施比较一下，例如 Win32 Fiber 和 `boost::context`。重点是协程挂起后、转移控制权前能否执行逻辑。

许多有栈协程框架把“挂起当前协程”和“恢复另一个协程”合并成一次上下文切换。当前协程挂起后，控制权立即转给另一个协程，中间通常没有机会插入额外逻辑。

如果要在有栈协程上实现类似的异步文件读取，就得先启动操作，再挂起协程。异步操作可能在协程真正挂起、可以安全恢复之前就在另一线程完成，两者形成竞争，需要线程同步来仲裁。

一种可能的办法是引入跳板上下文（trampoline context），等发起方挂起后由它代为启动操作。但这需要额外的基础设施和上下文切换，新增开销可能比原本想避开的同步成本还高。

## 避免内存分配

异步操作通常需要一份独立状态来跟踪进度。这份状态必须活过整个操作，只能在操作结束后释放。

例如，调用异步 Win32 I/O 函数时，需要分配一个 `OVERLAPPED` 结构并传入其指针。调用方必须保证操作完成前这个指针始终有效。

传统回调式 API 通常把这份状态分配在堆上，以满足生命周期要求。大量操作意味着反复分配和释放；性能敏感时，可以改用自定义分配器，从对象池取得这些状态对象。

使用协程时，局部变量在协程挂起期间仍能存活。操作状态可以利用这一点，不必单独分配堆内存。

把每次操作的状态放进 **Awaiter** 对象，就相当于在 `co_await` 表达式存续期间向协程帧“借”一块内存。操作完成后协程恢复，**Awaiter** 被销毁，这块空间又能交给其他局部变量使用。

协程帧本身可能仍在堆上，但只需分配一次，同一个协程就能用它执行许多异步操作。

换个角度看，协程帧就是一种高性能的区域（arena）分配器。编译器在编译期算出所有局部变量所需的总空间，再按生命周期把这块内存复用给不同变量，运行时没有额外分配开销。自定义分配器很难做到同样的事。

## 示例：实现一个简单的线程同步原语

了解 `co_await` 的主要机制后，我们来实现一个基本的 Awaitable 同步原语：异步手动重置事件（asynchronous manual-reset event）。

多个并发协程都可以等待这个事件。等待时，协程挂起，直到某个线程调用 `.set()`，此时所有等待中的协程恢复。如果事件已经被 `.set()` 置位，后来执行 `co_await` 的协程应直接继续，不再挂起。

理想的实现还应满足 `noexcept`，不需要额外堆分配，并且无锁。

**2017 年 11 月 23 日编辑：补充 `async_manual_reset_event` 的用法示例。**

用法大致如下：
```c++
T value;
async_manual_reset_event event;

// A single call to produce a value
void producer()
{
  value = some_long_running_computation();

  // Publish the value by setting the event.
  event.set();
}

// Supports multiple concurrent consumers
task<> consumer()
{
  // Wait until the event is signalled by call to event.set()
  // in the producer() function.
  co_await event;

  // Now it's safe to consume 'value'
  // This is guaranteed to 'happen after' assignment to 'value'
  std::cout << value << std::endl;
}
```

先看事件的两种状态：“未置位”和“已置位”。

处于“未置位”状态时，事件维护一个等待协程列表，列表可能为空。这些协程都在等它变为“已置位”。

处于“已置位”状态时，不会有等待协程，因为此时对事件执行 `co_await` 可以直接继续。

这两种状态可以用一个 `std::atomic<void*>` 表示：
- 为“已置位”保留一个特殊指针值。这里使用事件的 `this` 指针，因为它不可能与任何链表节点同址；
- 其他值表示事件“未置位”，此时指针指向等待协程单链表的表头。

链表节点放在协程帧内的 `awaiter` 对象中，因此不必再从堆上单独分配节点。

先定义类接口：
```c++
class async_manual_reset_event
{
public:

  async_manual_reset_event(bool initiallySet = false) noexcept;

  // No copying/moving
  async_manual_reset_event(const async_manual_reset_event&) = delete;
  async_manual_reset_event(async_manual_reset_event&&) = delete;
  async_manual_reset_event& operator=(const async_manual_reset_event&) = delete;
  async_manual_reset_event& operator=(async_manual_reset_event&&) = delete;

  bool is_set() const noexcept;

  struct awaiter;
  awaiter operator co_await() const noexcept;

  void set() noexcept;
  void reset() noexcept;

private:

  friend struct awaiter;

  // - 'this' => set state
  // - otherwise => not set, head of linked list of awaiter*.
  mutable std::atomic<void*> m_state;

};
```

这个接口很直接。关键在于 `operator co_await()`，它返回一个尚未定义的 `awaiter` 类型。

下面定义 `awaiter`。

### 定义 Awaiter

`awaiter` 首先要知道自己等待哪个 `async_manual_reset_event`，因此需要保存事件引用，并用构造函数初始化。

它还充当 `awaiter` 单链表的节点，所以要保存指向下一个 `awaiter` 的指针。

它还要保存等待协程的 `coroutine_handle`，这样事件变为“已置位”时才能恢复协程。这里不关心协程的 Promise 类型，因此使用 `coroutine_handle<>`，也就是 `coroutine_handle<void>` 的简写。

最后，它要实现 **Awaiter** 接口的三个特殊方法：`await_ready`、`await_suspend` 和 `await_resume`。这个 `co_await` 表达式不产生值，所以 `await_resume` 返回 `void`。

合在一起，`awaiter` 的基本接口如下：
```c++
struct async_manual_reset_event::awaiter
{
  awaiter(const async_manual_reset_event& event) noexcept
  : m_event(event)
  {}

  bool await_ready() const noexcept;
  bool await_suspend(std::experimental::coroutine_handle<> awaitingCoroutine) noexcept;
  void await_resume() noexcept {}

private:

  const async_manual_reset_event& m_event;
  std::experimental::coroutine_handle<> m_awaitingCoroutine;
  awaiter* m_next;
};
```

对事件执行 `co_await` 时，如果事件已经置位，就不该挂起协程。因此，事件已置位时让 `await_ready()` 返回 `true`：
```c++
bool async_manual_reset_event::awaiter::await_ready() const noexcept
{
  return m_event.is_set();
}
```

接着看 `await_suspend()`，Awaiter 的核心逻辑通常都在这里。

需要先把等待协程的句柄存入 `m_awaitingCoroutine` 以便后续在事件置位时调用 `.resume()`。

随后以原子方式把当前 Awaiter 加入等待链表。入队成功就返回 `true`，让协程保持挂起；如果发现事件在此期间已经变为“已置位”，则返回 `false`，立即恢复协程。
```c++
bool async_manual_reset_event::awaiter::await_suspend(
  std::experimental::coroutine_handle<> awaitingCoroutine) noexcept
{
  // Special m_state value that indicates the event is in the 'set' state.
  const void* const setState = &m_event;

  // Remember the handle of the awaiting coroutine.
  m_awaitingCoroutine = awaitingCoroutine;

  // Try to atomically push this awaiter onto the front of the list.
  void* oldValue = m_event.m_state.load(std::memory_order_acquire);
  do
  {
    // Resume immediately if already in 'set' state.
    if (oldValue == setState) return false; 

    // Update linked list to point at current head.
    m_next = static_cast<awaiter*>(oldValue);

    // Finally, try to swap the old list head, inserting this awaiter
    // as the new list head.
  } while (!m_event.m_state.compare_exchange_weak(
             oldValue,
             this,
             std::memory_order_release,
             std::memory_order_acquire));

  // Successfully enqueued. Remain suspended.
  return true;
}
```

加载旧状态时使用 acquire 内存序。这样一旦读到特殊的“已置位”值，就能看见调用 `set()` 之前发生的写入。

比较交换成功时需要 release 语义，保证后续调用 `set()` 的线程能看见对 `m_awaitingCoroutine` 的写入，以及此前对协程状态的写入。

### 补全事件类

`awaiter` 定义完成后，回头实现 `async_manual_reset_event` 的其余方法。

构造函数把状态初始化为带空等待链表的“未置位”，即 `nullptr`；或者初始化为“已置位”，即 `this`。
```c++
async_manual_reset_event::async_manual_reset_event(
  bool initiallySet) noexcept
: m_state(initiallySet ? this : nullptr)
{}
```

`is_set()` 很简单：状态等于特殊值 `this` 就表示事件已经置位。
```c++
bool async_manual_reset_event::is_set() const noexcept
{
  return m_state.load(std::memory_order_acquire) == this;
}
```

`reset()` 只在当前状态为“已置位”时把它改回空链表表示的“未置位”，其他状态保持不变。
```c++
void async_manual_reset_event::reset() noexcept
{
  void* oldValue = this;
  m_state.compare_exchange_strong(oldValue, nullptr, std::memory_order_acquire);
}
```

`set()` 用特殊值 `this` 交换当前状态，使事件变为“已置位”，然后检查旧状态。如果旧状态中有等待协程，就在返回前逐一恢复它们。
```c++
void async_manual_reset_event::set() noexcept
{
  // Needs to be 'release' so that subsequent 'co_await' has
  // visibility of our prior writes.
  // Needs to be 'acquire' so that we have visibility of prior
  // writes by awaiting coroutines.
  void* oldValue = m_state.exchange(this, std::memory_order_acq_rel);
  if (oldValue != this)
  {
    // Wasn't already in 'set' state.
    // Treat old value as head of a linked-list of waiters
    // which we have now acquired and need to resume.
    auto* waiters = static_cast<awaiter*>(oldValue);
    while (waiters != nullptr)
    {
      // Read m_next before resuming the coroutine as resuming
      // the coroutine will likely destroy the awaiter object.
      auto* next = waiters->m_next;
      waiters->m_awaitingCoroutine.resume();
      waiters = next;
    }
  }
}
```

最后实现 `operator co_await()`，它只需构造并返回一个 `awaiter`。

```c++
async_manual_reset_event::awaiter
async_manual_reset_event::operator co_await() const noexcept
{
  return awaiter{ *this };
}
```

至此，我们得到了一个 Awaitable 的异步手动重置事件：实现无锁，不需要额外内存分配，并且是 `noexcept` 的。

想试运行代码，或者查看 MSVC 和 Clang 生成的结果，可以打开 [Godbolt 上的完整示例](https://godbolt.org/g/Ad47tH)。

[cppcoro](https://github.com/lewissbaker/cppcoro) 库也提供了这个类，以及 `async_mutex`、`async_auto_reset_event` 等其他实用的 Awaitable 类型。

## 结语

本文以 **Awaitable** 和 **Awaiter** 两个概念为线索，说明了 `operator co_await` 的定义与实现方式。

随后实现的异步线程同步原语把操作状态放在协程帧中的 Awaiter 对象里，避开了额外的堆分配。

掌握这些转换规则后，`co_await` 的挂起与恢复过程就有了可追踪的路径。

下一篇会讨论 **Promise** 概念，以及协程类型的作者如何定制协程本身的行为。

## 致谢

特别感谢 Gor Nishanov，过去几年里他耐心而热情地回答了我许多关于协程的问题。

也感谢 Eric Niebler 审阅本文初稿并提供反馈。
