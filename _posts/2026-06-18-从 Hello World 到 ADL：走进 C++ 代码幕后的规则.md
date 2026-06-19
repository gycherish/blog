---
media_subpath: /assets/img/notes
author: gycherish
title: 从 Hello World 到 ADL：走进 C++ 代码幕后的规则
tags:
  - c++
  - adl
  - cpo
  - tag_invoke
categories:
date: 2026-06-18 14:00
---

## 从 Hello World 说起

相信每一个 C++ 程序员在入门时，都写过类似这么一段代码：

```cpp
#include <iostream>
int main() {
    std::cout << "Hello World" << std::endl;
}
```

这段代码太常见了，常见到几乎每一个人——无论是初学者，还是工作多年的 C++ 程序员，都没有认真想过它背后的原理。

同样的“怪事”也发生在自定义类型上：

```cpp
namespace math {
    struct Complex { 
        int real;
        int imag;
    };

    Complex operator+(const Complex& a, const Complex& b) { 
        return {a.real + b.real, a.imag + b.imag};
    }
}

int main() {
    math::Complex a{1, 2};
    math::Complex b{3, 4};
    auto c = a + b;
}
```

它们的答案都来自同一个机制：**ADL（Argument Dependent Lookup）**。

## 什么是 ADL
**ADL** 是 C++ 里一个非常重要的名称查找机制，它允许你在调用函数时，从实参类型所属的命名空间中进行查找，并自动把相应函数纳入候选集，而不需要显式地指定被调用函数的作用域或限定符。

[C++ 标准草案 `[basic.lookup.argdep]/1`](https://eel.is/c++draft/basic.lookup.argdep) 中的定义如下：

> *When the postfix-expression in a function call is an unqualified-id, and unqualified lookup for the name in the unqualified-id does not find any*

> 1. *declaration of a class member, or*
> 2. *function declaration inhabiting a block scope, or*
> 3. *declaration not of a function or function template*

> *then lookup for the name also includes the **result of argument-dependent lookup in a set of associated namespaces that depends on the types of the arguments** (and for type template template arguments, the namespace of the template argument)*

[cppreference](https://en.cppreference.com/cpp/language/adl) 中的定义如下:

> *Argument-dependent lookup (ADL), also known as Koenig lookup[1], is the set of rules for looking up the unqualified function names in function-call expressions, including implicit function calls to overloaded operators. These function names are looked up in the namespaces of their arguments in addition to the scopes and namespaces considered by the usual unqualified name lookup.*

标准中关于 ADL 更详细的介绍可参考相关链接，本文不再赘述。

## 到底发生了什么

考虑到这里涉及到 C++ 的运算符重载，需要先讲下[运算符重载的规则](https://eel.is/c++draft/over.match.oper)。简单来说，当运算符表达式被解析时，编译器会从以下候选列表中选择候选函数：

- 成员候选函数（操作数类型的成员）
- 非成员候选函数（普通查找 + ADL 查找）
- 内置候选函数

关于运算符重载的规则，感兴趣的读者可以参考相关链接，本文不再赘述。

回到前面的示例：

> `std::cout << "Hello World";`

其中：

- `std::cout` 是一个全局变量，它的类型是 `std::ostream`
- `<<` 是 `operator<<` 运算符
- `"Hello World"` 是一个字符串字面量，它的类型是 `const char[12]`，不过在函数调用时会退化成 `const char*`

编译器将上述代码经过一系列处理后，最终的调用形式如下：

> `std::operator<<(std::cout, "Hello World");`

那么上述过程到底是怎么发生的呢？

1. 解析 `<<` 表达式，编译器发现其为 `operator<<` 运算符，因此 *内置候选函数* 会被加入候选列表。
2. 由于左操作数是 std::ostream 类且具有很多 `operator<<` 重载，因此它的 *成员候选函数* 会被加入候选列表。
3. 由于 `<<` 是一个非限定名字，且标准文档的 3 种情况均不存在，因此编译器还会考虑 ADL 查找。
4. 编译器发现 `std::ostream` 位于 `std` 命名空间中，因此开始从 `std` 命名空间中进行查找。
5. 在 `std` 命名空间中存在很多 `operator<<` 重载，因此这些 *非成员候选函数* 也被加入候选列表。
6. 编译器对所有候选函数进行重载决议，发现 `std` 命名空间中的 `std::ostream& operator<<(std::ostream&, const char*)` 满足最佳匹配规则，因此最终调用该函数。

## 为什么要有 ADL

这是一个非常深刻的问题，理解 ADL 存在的原因比记住其规则本身更加重要。如果没有 ADL，C++ 中的很多核心语法和泛型编程模式将无法工作。

### 语法层面的需求：统一的运算符语法

考虑内置类型 int 的加法：

```cpp
int a = 1;
int b = 2;
int c = a + b;
int d = a + b + c;
```

以上写法非常自然且容易理解。同理，我们也想对自定义类型也能写出类似的表达：

```cpp
math::Complex a{1, 2};
math::Complex b{3, 4};
math::Complex c = a + b;
math::Complex d = a + b + c;
```

但是，如果没有 ADL，我们将不得不这样写：

```cpp
math::Complex c = math::operator+(a, b);
math::Complex d = math::operator+(math::operator+(a, b), c);
```

很显然，这对于阅读代码来说是灾难性的。有了 ADL 后，无论是内置类型，还是用于自定义类型，都可以以最自然的方式进行表达。

### 设计哲学层面的需求：类的“外部接口”

C++ 的核心设计哲学之一是：一个类的接口不仅包括其成员函数，还包括与其协同工作的非成员函数。 这被称为[接口原则(Interface Principle)](http://www.gotw.ca/publications/mill02.htm)。

像 `operator<<`、`swap`、`begin/end` 这些函数，它们虽然不作为类的成员，但它们是该类公共接口的重要组成部分。ADL 的作用，就是将这些“外部接口函数”与类本身绑定在一起。

如果没有 ADL，类的“接口”就会被迫局限于成员函数，这严重限制了 C++ 表达力和封装能力。

### 泛型编程层面的需求：统一的操作契约

ADL 在 C++ 的泛型编程中扮演着至关重要的角色。它是“定制点”（Customization Point）机制的核心实现技术。

在编写通用模板时，我们通常不知道处理的具体类型是什么。我们希望代码能调用“该类型最适合的”函数版本，而不是强制使用某个固定的版本。比如经典的 `swap` 模式：

```cpp
namespace myns {
    struct LargeObject {
        // 定制的 swap 实现，性能最优
        friend void swap(LargeObject& a, LargeObject& b) {
            // ...
        }
    };
}

template <class T>
void myalgo(T& a, T& b) {
    // 把 std::swap 引入候选，作为兜底实现
    using std::swap;
    // 无限定符的调用：ADL 优先在 T 所属命名空间找用户特化版本
    swap(a, b);
}

int main() {
    myns::LargeObject a, b;
    // 内部调用定制的 swap 实现
    myalgo(a, b);
}
```

这里有个问题要解释下，即为何要写 `using std::swap;`：当调用 `swap(a, b)` 时，会从 T 所属命名空间查找是否有定制的 swap 实现，如果没有，考虑以下情况：

- 省略了 `using std::swap;`：由于 T 不在 `std` 命名空间中，因此不会通过 ADL 查找到 `std::swap`，此时如果有全局 swap 函数，则会调用全局 swap 函数，但是不排除全局 swap 表达的语义错误，如果没有全局 swap 函数，则直接编译报错
- 写了 `using std::swap;`：由于 std::swap 是模板函数，即使通过 ADL 没有找到适合 T 的 swap 函数，编译器也会从 std::swap 中实例化一份针对 T 类型的 swap，只不过可能性能较差

## ADL 的现代演进：定制点对象（CPO）

有了 ADL，我们可以在经典的 `swap` 模式中为不同的类型提供不同的特化版本以满足性能需求。然而，这个模式有以下问题：

- 噪音大：需要在每个使用 swap 的模板函数里写 `using std::swap;`。
- 易出错：如果忘记写 `using std::swap;`，`swap(a,b)` 可能调用失败，或者更糟——找到某个不相关的全局 swap 函数。
- 无法传递：你不能像传递普通函数指针或函数对象那样，将最优的 `swap` 算法作为参数传递给其他函数。
- 语法不统一：对于不同的操作，你都需要记住这个先 using 再调用的固定写法。

CPO 正是为了解决这些问题而引入的。

### CPO 的核心思想

CPO 的全称叫“定制点对象（Customization Point Object）”，比起通过普通函数配合 ADL 实现的“定制点”，CPO 则通过将定制点作为普通 C++ 对象来实现，即 CPO 的本质是一个函数对象。它的 `operator()` 操作符内部封装了“优先使用 ADL 查找，否则使用默认实现”的逻辑。

为了让大家更清楚地理解 CPO 的工作原理，我以 C++20 中的 `std::ranges::swap` 的实现原理（伪码，严格来讲实现并不正确，这里只展示原理）进行说明：

```cpp
namespace std::ranges {
    template<typename T, typename U>
    concept adl_swap = requires(T&& t, U&& u) {
        swap(t, u);
    };

    struct swap_t {
        template <typename T, typename U>
        void operator()(T&& a, U&& b) const {
            if constexpr (adl_swap<T, U>) {
                // 优先使用 ADL 查找定制的 swap 实现
                swap(a, b);
            }
            else {
                // fallback 实现
                auto tmp = a;
                a = b;
                b = tmp;
            }
        }
    };

    // CPO
    inline constexpr swap_t swap{};
}
```

使用方：

```cpp
namespace myns {
    struct LargeObject {
        // 定制的 swap 实现，性能最优
        friend void swap(LargeObject& a, LargeObject& b) {
            // ...
        }
    };
}

int main() {
    myns::LargeObject a, b;
    std::ranges::swap(a, b);
}
```

可以看到，跟上文中不带 CPO 的 swap 模式相比，CPO 的 swap 模式更简洁，写法更加统一，没有了 `using std::swap;` 这个被引入用户侧代码的噪音以及可能的出错风险。

由于 `std::ranges::swap` 是一个普通的 C++ 对象，因此外部调用 `std::ranges::swap(a, b)` 时，编译器不会走 ADL，而是选择了严格匹配的成员函数 `std::ranges::swap_t::operator()(T&&, U&&)`。所有 ADL 的查找都被封装在了 `std::ranges::swap_t::operator()` 中，用户完全不需要关心实现的细节。

### CPO 与传统 ADL 的对比

| 对比点 | 传统 ADL 写法 | CPO 写法 | CPO 的优势 |
| --- | --- | --- | --- |
| 调用形式 | `using std::swap; swap(a, b);` | `std::ranges::swap(a, b);` | 调用点更统一，不要求用户记住“两步法” |
| 查找入口 | 非限定函数调用触发 ADL | 调用一个标准库提供的函数对象 | 入口固定，可读性更强 |
| 可定制性 | 用户在自己类型命名空间放同名函数 | 用户按 CPO 规定提供成员函数、ADL 函数或 traits | 仍然保留类型自定义能力 |
| 误命中风险 | 可能被无关命名空间里的同名函数影响 | CPO 内部按标准规定的顺序和约束查找 | 更可控，减少意外 ADL 命中 |
| fallback 逻辑 | 需要调用者手写 `using std::swap` | CPO 内部封装 fallback 顺序 | 不容易漏写兜底逻辑 |
| 约束检查 | 普通 ADL 命中后才可能在函数体里报错 | CPO 通常配合 concepts | 错误更早、更清晰 |
| 接口稳定性 | 裸函数名容易受作用域污染影响 | `std::ranges::swap` 是限定调用 | 更稳定，不容易被局部名字遮蔽 |
| 封装性 | 查找规则暴露给调用者 | 查找和 fallback 规则封装在 CPO 内部 | 使用者只关心语义，不必关心查找细节 |
| 诊断体验 | 命中错误重载时，报错可能很长 | 约束失败通常更接近“这个操作不可用” | 模板报错更容易读 |
| 适合场景 | 传统泛型代码、旧标准库定制点 | C++20 ranges、现代标准库定制点 | 更适合现代库设计 |

### 总结

传统 ADL 是“把查找能力交给调用者”；CPO 是“把查找、约束和兜底策略封装成一个稳定对象”。 CPO 并不是完全抛弃 ADL，而是把 ADL 收进一个受控的实现细节里：外部调用者看到的是稳定的类似  `std::ranges::swap` 的调用，内部仍然可以在合适的位置利用 ADL 完成类型定制。

## 从 CPO 到 tag_invoke

CPO 虽然解决了传统 ADL 的一些问题，但是依然存在两个问题尚未解决：

1. 每个库内部都通过 ADL 调用同名的自由函数以实现定制能力，但是这意味着每个定制点的名字都需要全局保留。而且，当多个库使用了同名的定制点，还会导致冲突，更严重的是调用的定制点的行为完全不符合预期。 
2. ADL 不允许编写对自定义透明的包装类型

问题 1 的解决最为迫切。为了解决这个问题，社区引入了一种新的用于提供定制功能的编程范式，即  **[tag_invoke](https://wg21.link/p1895)**。

问题 2 有些晦涩且使用面比较小，有兴趣的读者可以自行阅读原文，这里就不展开。

### tag_invoke 的核心思想

`tag_invoke` 核心思想是：**为所有需要定制的功能提供一个统一的 ADL 入口**，即 `tag_invoke`。其签名为：

```cpp
tag_invoke(cpo_tag, args...)
```

其中第一个参数是 CPO 对象本身，表示要定制的操作。

根据上文描述：`swap_t` CPO 为了达到定制效果，保留了一个名为 `swap` 的自由函数，也就是说用户必须定义同名的 `swap` 函数才能实现定制。类似的，C++ 标准库中还存在大量其他不同名字的 CPO，比如：

> begin/end/size/data/empty...

如果每个定制功能都需要保留一个函数名，可想而知，程序可能会出现非常隐秘的 BUG。如果再把第三方库考虑进去，结果只会更严重，也为开发者带来更多的心智负担。`tag_invoke` 通过其第一个参数巧妙地解决了这个问题。

假设存在两个三方库都允许定制 `swap` 功能，那么，站在定制方的角度，其应该提供两个函数：
```cpp
// 用户自定义类型
struct UserType;

// 用于定制标准库的行为
tag_invoke(liba::swap_t{}, UserType&, UserType&);

// 用于定制第三方库的行为
tag_invoke(libb::swap_t{}, UserType&, UserType&);

// 实际使用
UserType a, b;
liba::swap(a, b); // liba 版本
libb::swap(a, b); // libb 版本
```

其中一个库的实现方式可能是这样（伪码）：

```cpp
namespace liba {
    void tag_invoke();

    struct swap_t {
        template <class T, class U>
        constexpr auto operator()(T&& a, U&& b) const {
            return tag_invoke(*this, std::forward<T>(a), std::forward<U>(b));
        }
    };

    inline constexpr swap_t swap{};
}
```

当用户调用 `liba::swap` 时，会触发以下过程：

1. 调用 `liba::swap_t::operator()`。
2. 调用 `tag_invoke`，此时触发 ADL 查找。
3. 找到用户版本的 `tag_invoke(liba::swap_t{}, UserType&, UserType&)` 并调用。

如果库中还提供其他定制功能，站在用户角度，永远只需要实现名为 `tag_invoke` 的函数即可，而且针对不同库的不同功能做定制，`tag_invoke` 可以通过第一个参数做区分，语义非常明确。至此，`tag_invoke` 将不同定制点的 ADL 入口收敛到同一个名字上，缓解了定制点名称冲突和协议分散的问题。

需要注意的是，标准库其实并没有采用 `tag_invoke`，见下文。

## 万变不离其宗：定制的最优解

前面我们提到的 ADL 以及基于 ADL 的 CPO 和 `tag_invoke`，他们出现的核心动机都是为了定制。但是从 ADL 到 CPO 到 `tag_invoke`，问题真的都解决了吗？答案是否定的。

但凡用 C++ 写过稍大一点项目的开发者都知道，使用了 C++ 模板的代码的编译速度真的非常慢。而基于 ADL 的 `tag_invoke` 加剧了这一现象：

- `tag_invoke` 的代价在于，它把很多原本不同名字的定制点都压到同一个 ADL 名字下。协议统一了，但每次调用 CPO 时，编译器都要围绕 `tag_invoke(tag, args...)` 做候选收集、约束检查和重载决议；一旦相关命名空间里存在多个泛型 `tag_invoke` 重载，或者这些重载本身带有复杂的 Concepts / SFINAE 条件，就会产生额外的模板实例化成本。在大型模板库中，这类成本会不断累积，成为编译速度和诊断体验上的负担。

那么有没有更好的方案呢？答案是：使用**成员函数**！写到这里，我不禁感慨，这么朴实无华、姿势最佳、性能最优、最天经地义的做法竟然在很多场景下被忽略。

为了印证我的说法，给大家看一下标准库的代码：

```cpp
struct _Begin
{
private:
    template<typename _Tp>
    static constexpr bool
    _S_noexcept()
    {
        if constexpr (is_array_v<remove_reference_t<_Tp>>)
            return true;
        else if constexpr (__member_begin<_Tp>)
            return noexcept(__decay_copy(std::declval<_Tp&>().begin()));
        else
            return noexcept(__decay_copy(begin(std::declval<_Tp&>())));
    }

public:
    template<__maybe_borrowed_range _Tp>
        requires is_array_v<remove_reference_t<_Tp>> || __member_begin<_Tp>
            || __adl_begin<_Tp>
    [[nodiscard]]
    constexpr auto
    operator()(_Tp&& __t) const noexcept(_S_noexcept<_Tp&>())
    {
        if constexpr (is_array_v<remove_reference_t<_Tp>>)
        {
            static_assert(is_lvalue_reference_v<_Tp>);
            return __t + 0;
        }
        else if constexpr (__member_begin<_Tp>)
            return __t.begin();
        else
            return begin(__t);
    }
};
```

可以看到，标准库中 `begin` 这个定制点的实现就是优先匹配成员函数，然后才走 ADL。这些写法在标准库中大量存在。就连 [execution](http://wg21.link/p2300) 提案的开源实现 [stdexec](https://github.com/nvidia/stdexec) 也把基于 ADL 的 `tag_invoke` 替换为了基于成员函数的定制。

当然，我这里不是说成员函数能完全替代 ADL/CPO/tag_invoke，而是说应当在能使用成员函数的地方优先使用成员函数。如果使用成员函数很别扭甚至做不到，ADL/CPO/tag_invoke 依然是一个好选择。

## 总结

本文尝试带大家理解 C++ 中的 ADL 以及如何使用 ADL 对功能进行定制，但是考虑到 C++ 的复杂性，本文的内容依然非常浅显，还有很多内容没有涉及到。因此，本文权当抛砖引玉，希望以后大家在写 C++ 项目时在能够看懂 ADL 的同时，还能够根据实际需求将其应用到自己的项目中。
