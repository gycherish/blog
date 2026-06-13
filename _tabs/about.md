---
# the default layout is 'page'
icon: fas fa-info-circle
order: 4
---

我是一名 C/C++ 系统开发工程师, 有 10 年+ 系统级开发经验, 目前专注 **AI 存储** 与 **AI 高性能通信** 两个方向。

这个站点是我的技术笔记, 主要记录 C++、AI、存储、高性能网络与虚拟化方向的学习与实践。

## 我在关注什么

- **AI 存储** —— 大模型训练 checkpoint 的高效读写与故障恢复; 推理 KV cache 的分层缓存(显存/内存/SSD/远端)与跨机池化传输(PD 分离); 面向 AI 负载的分布式/并行文件系统。持续研读 3FS、Mooncake、vLLM 等系统。
- **AI 高性能通信** —— RDMA / RoCEv2 / InfiniBand 与 ibverbs 编程; GPUDirect RDMA/Storage; NCCL 集合通信; NVMe-oF、SPDK 用户态存储栈; KV/张量传输库(Mooncake Transfer Engine、NIXL)。
- **高性能与并发** —— Linux/Windows 系统编程；内核旁路技术；高性能异步 IO（iocp/io_uring）；现代 C++（C++20 协程、C++26 `std::execution`）。

## 一些经历

过去几年主要深耕**企业级容灾**, 围绕数据保护这条主线: 块级/文件级数据复制、写时复制快照与一致性组、持续数据保护(CDP)、故障检测与主备切换, 以及 RPO/RTO 优化; 也从零实现过 iSCSI target 协议栈、对接内核过滤驱动的块级变更捕获(CBT)、扩展 QEMU/KVM 无代理保护。

这套围绕**一致性快照与快速恢复**的命题, 与大模型训练 checkpoint、推理 KV cache 的工程问题本质同源; 更早做过的 **DPDK** 内核旁路高性能数据面, 也与 RDMA / GPUDirect 等 AI 传输栈一脉相承——这些底层积累, 正是我深入 AI 存储与高性能通信的根基。

欢迎 **AI 存储 / AI Infra / 高性能通信** 方向的技术交流与合作。
