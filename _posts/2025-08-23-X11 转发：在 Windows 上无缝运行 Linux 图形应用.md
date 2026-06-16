---
media_subpath: /assets/img/notes
author: gycherish
title: X11 转发：在 Windows 上无缝运行 Linux 图形应用
tags:
  - x11
  - ssh
categories:
date: 2025-08-23 23:06
---

## 什么是  X11
X11(X Window System Version 11)是一种网络透明的窗口系统，主要用于 Unix-like 操作系统。它采用客户端-服务器模型，允许应用程序(客户端)在远程服务器上运行，而图形界面可以显示在本地计算机上。

## X11 的主要特点
1. 网络透明性：可以在远程运行程序而显示在本地
2. 客户端-服务器架构
3. 支持多种硬件平台
4. 可扩展性强

## 什么是 X11 转发
X11 转发是通过 SSH 隧道安全地传输 X11 图形界面数据的技术，使得远程图形程序可以在本地显示。通过使用 X11 转发，我们可以在没有桌面环境的远程 Linux 操作系统中运行带图形化界面的程序，就像在本地运行一样，非常方便日常的开发维护工作。

## X11 转发架构
基于 SSH 的 X11 转发架构如下图所示：
![x11-arch](x11-arch.svg)

其中 X Server 是 X11 的服务端，负责将客户端的图形化界面渲染出来；X Client 是 X11 的客户端，通过 X11 的协议将要渲染的图形化界面发给 X Server，由 X Server 负责渲染出来；X Server 和 X Client 的数据通过 SSH 通道加密传输。

## 使用 X11 转发
本文使用 Rocky Linux 8.6 最小化安装版本作为 X11 的远程机器来运行 X Client，个人 Windows10 开发机作为本地机器运行 X Server，通过 SSH 将远程机器的图形化界面显示到本地。

### 客户端配置
为了实现 X11 转发功能，需要对客户端机器做一些配置。

####  开启 X11 转发功能
打开客户端 sshd 服务的配置文件( /etc/ssh/sshd_config)，确保开启 X11 转发功能，若未开启，则手动设置好以下配置项:
```bash
X11Forwarding yes
```

#### 安装 xauth
xauth 是一个用于管理 X11 授权的工具，当你使用 SSH 的 X11 转发功能时，SSH 需要 xauth 来安全地处理 X11 图形的转发，安装命令如下：
```bash
dnf install -y xauth
```

创建授权文件：
```bash
touch ~/.Xauthority
```

查看 xauth 安装位置：
```bash
which xauth
```

安装完成后需要修改 sshd 服务配置文件，确保 sshd 服务能够正确找到 xauth 程序，配置项如下：
```bash
XAuthLocation /usr/bin/xauth
```

#### 安装 xclock
xclock 工具用于测试 X11 转发功能，当一切准备就绪时，在客户端机器执行 xclock 命令将会在本机显示一个时钟，安装命令如下：
```bash
dnf install -y --enablerepo=powertools xclock
```

#### 重启 sshd 服务
以上配置完成后需要重启 sshd 服务使配置生效：
```bash
systemctl restart sshd
```

### 服务端配置
为了实现 X11 转发功能，需要对服务端机器做一些配置。

#### 安装 X Server
本机系统为 Windows10，可以选择 [VcXsrv](https://vcxsrv.com/) 作为 X Server，该 X Server 开源免费，可到官网直接下载安装，具体步骤不再赘述，安装完成后，直接启动即可。

#### 安装  SSH 客户端
由于 X11 转发需要连接客户端机器的 SSH 服务，而 Windows 系统默认没有可用的 SSH 客户端，因此需要先安装一个 SSH 客户端，推荐使用 [Putty](https://www.putty.org/) 作为 Windows 系统的 SSH 客户端，不仅免费还可以商用。对于经常使用 [Git](https://git-scm.com/) 的开发者，可以直接使用 Git Bash 作为 SSH 客户端。具体安装步骤不再赘述。

### 发起 X11 转发
以上配置准备就绪后，可以直接使用 SSH 客户端向 SSH 服务端发起 X11 转发了。为了方便测试，客户端的 IP 地址设为 192.168.3.5，服务端的 IP 地址设为 192.168.3.4，二者处于同一个子网。

#### 重要的环境变量：DISPLAY 
DISPLAY 环境变量用于配置 X Server 的信息，正确设置了这个环境变量才能保证 X Client 能正确连接到 X Server 并将图形化界面显示出来，格式如下：
> hostname:display_number.screen_number

各字段解释如下：
- hostname: 用于指示 X Server 运行在哪里，对于本地 X Server，hostname 可以设置为 localhost 或 127.0.0.1，对于远程 X Server，hostname 为远程 X Server 的 IP 地址或主机名(域名)。
- display_number: 用于标识具体的 X Server 实例，一个系统理论上可以运行多个 X Server 实例，他们监听在不同的端口，通过该变量使 X Client 可以知道应该连哪个 X Server 实例。X Server 的默认端口是 6000，该变量一般直接用于表示 X Server 监听的端口号，默认 0 表示监听在 6000 端口，10 表示监听在 6010 端口。
- screen_number: 用于指示 X Server 将 X Client 的图形化界面渲染在哪个屏幕上，如果 X Server 监听了多个屏幕，通过该变量可以指定连接哪个屏幕，该变量默认为 0，一般不需要调整。

在不做任何修改的情况下，上文中运行的 X Server 默认监听在 localhost:6000 地址上，因此对应的 DISPLAY 变量的值为 localhost:0.0。

#### 使用 Git Bash 发起 X11 转发
上文中提到客户端需要安装 xauth，该工具用于 X11 转发时的授权流程。然而，授权一定是双向的，因此除了客户端需要有授权工具，服务端也需要存在，由于 Git  没有自带授权工具，因此使用 Git Bash 发起 X11 转发时，需要使用无授权模式的 X11 转发，打开 Git Bash 命令行窗口，执行以下命令：
```bash
export DISPLAY=localhost:0.0
ssh -Y root@192.168.3.5
```

输入密码或使用了 SSH key 授权连接成功后，直接执行 xclock 命令将会在本机屏幕上显示一个时钟：
![x11-git-xclock](x11-git-xclock.png)
#### 使用 Putty 发起 X11 转发
Putty 和 Git 不同的是，其作为一款 SSH 客户端内部自带了 X11 授权的功能，因此不需要额外安装类似 xauth 这样的工具就可以直接发起 X11 转发功能。对于其他的 SSH 客户端，如 XShell，甚至自带了 XServer，这意味着使用 [XShell](https://www.netsarang.com/en/xshell/) 做 X11 转发时甚至都不需要额外下载安装 X Server。以下是使用 Putty 发起 X11 转发的步骤：

打开 Putty，输入 X Client 的 IP 地址：
![x11-putty-1](x11-putty-1.png)

设置 X11 转发：
![x11-putty-2](x11-putty-2.png)

点击 Open 打开终端发起 SSH 连接，连接成功后，直接执行 xclock 命令将会在本机屏幕上显示一个时钟：
![x11-putty-3](x11-putty-3.png)

## X11 转发工作原理
下文将站在客户端的角度，通过测试来理解转发的原理，对 X11 技术本身的实现本文不做讨论。

### 转发前
为了观察网络连接的状态，需要先安装 netstat 工具，命令如下：
```bash
dnf install -y net-tools
```

在不开启 X11 转发的情况下，直接使用 Putty 连接客户端的 sshd 服务并查看 SSH 相关的连接状态(sshd 默认监听在 22 端口，这里直接搜 22 和 sshd)：
```bash
netstat -tlnap | grep 22 | grep sshd
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      10239/sshd
tcp        0      0 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
tcp6       0      0 :::22 
```

可以看到目前只有一个 SSH 连接存在，即当前发起的非 X11 转发的链接：(192.168.3.5:22, 192.168.3.4:60462)。

再查看 X11 相关的连接状态(X Server 监听在 6000 端口，这里直接搜 60)：
```bash
netstat -tlnap | grep 60
tcp        0     64 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
```

可以看到，没有连接存在，60462 端口是上面的 SSH 连接。

### 转发后
额外再开启一个 Putty 发起 X11 转发，继续查看SSH 连接状态：
```bash
netstat -tlnap | grep 22 | grep sshd
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      10239/sshd
tcp        0     64 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
tcp        0      0 192.168.3.5:22          192.168.3.4:51728       ESTABLISHED 11939/sshd: root [p
tcp6       0      0 :::22                   :::*
```

可以看到比上面多了一个 SSH 连接，这个 SSH 通道即用于交互普通的 shell 命令还用与转发 X Client 和 X Server 之间的数据。

再查看 X11 相关的连接状态：
```bash
netstat -tlnap | grep 60
tcp        0      0 127.0.0.1:6010          0.0.0.0:*               LISTEN      11818/sshd: root@pt
tcp        0      0 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
tcp6       0      0 ::1:6010                :::*                    LISTEN      11818/sshd: root@pt
```

可以看到多了一个 sshd 进程监听在了 6010 端口，这里体现了"转发"的内涵，即 X Client 并不是直接连到  X Server 的，而是直接连到这个 sshd 进程，对 X Client 而言，这个 sshd 进程就是 X Server，相当于一个反向代理，后续 X Client 和 X Server 之间的数据交互都由这个 sshd 进程负责转发。

根据上文对 DISPLAY 环境变量的介绍，当前发起 X11 转发的 shell 里的 DISPLAY 环境变量的值一定为 localhost:10.0：
```bash
echo $DISPLAY
localhost:10.0
```

后续直接在当前 shell 执行 xclock 命令，xclock 将根据这个变量向监听在 6010 端口的 sshd 进程发起连接。

### 运行 X Client
运行 xclock 后再次查看SSH 连接状态：
```bash
netstat -tlnap | grep 22 | grep sshd
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      10239/sshd
tcp        0     64 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
tcp        0      0 192.168.3.5:22          192.168.3.4:61620       ESTABLISHED 11814/sshd: root [p
tcp6       0      0 :::22                   :::*                    LISTEN      10239/sshd
```

连接状态不变，符合预期，用于转发数据的 SSH 通道即为当前 SSH 连接对应的通道，无需新增新的连接。

再查看 X11 相关的连接状态：
```bash
netstat -tlnap | grep 60
tcp        0      0 127.0.0.1:6010          0.0.0.0:*               LISTEN      11944/sshd: root@pt
tcp        0     64 192.168.3.5:22          192.168.3.4:60462       ESTABLISHED 11732/sshd: root [p
tcp6       0      0 ::1:6010                :::*                    LISTEN      11944/sshd: root@pt
tcp6       0      0 ::1:6010                ::1:44044               ESTABLISHED 11944/sshd: root@pt
tcp6       0      0 ::1:44044               ::1:6010                ESTABLISHED 12277/xclock

```

可以看到，这里多了一个由 xclock 建立在 6010 端口的连接，验证了上文的说法。

### 总结
X11 转发时的进程关系如下：
![x11-process](x11-process.svg)

## 排错技巧
配置 X11 转发时难免会遇到没有效果的情况，此时可以通过以下方法尝试进行排错：
- 直接使用 ssh 命令发起 x11 转发时可以添加 -v 选项让 ssh 输出更详细的日志，-v 表示输出 debug1 日志，-vv 输出 debug1 和 debug2 日志，-vvv 输出 debug1、debug2 和 debug3 日志，通过观察日志，能够精准定位问题。
- 查看 DISPLAY 环境变量，如果该值为空，则 X11 转发一定没生效，这种情况大概率是发起 X11 转发时没设置该环境变量。
- 所有配置都没问题，但是看不到图形化界面，此时可以考虑是否有其他人也在使用 X11 转发，并且你调用的命令和别人调用的命令相同，对于有些单例进程(同一时间只允许运行一份)，多次调用是没有效果的，需要先把运行中的进程杀掉再重新运行。