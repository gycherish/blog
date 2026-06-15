---
media_subpath: /assets/img/notes
author: gycherish
title: iSCSI 实操：感受 iSCSI 的强大能力
tags:
  - iscsi
  - storage
  - linux
categories:
date: 2026-06-15 23:30
---

上篇讲过 iSCSI 本质就是把 SCSI 磁盘命令封装进 TCP/IP，让网络另一头的存储看起来像本地硬盘。这篇文章不再只讲概念，而是用两台真实虚拟机完整跑一遍流程，让读者能够直观地感受到 iSCSI 的效果。本次实验环境：

| 角色 | 系统 | IP | 说明 |
| --- | --- | --- | --- |
| iSCSI Target | AlmaLinux 10.1 | `192.168.1.115` | 提供远程 LUN |
| iSCSI Initiator | AlmaLinux 10.1 | `192.168.1.135` | 连接并使用远程磁盘 |
| iSCSI Initiator | Windows 10 | `192.168.1.152` | 连接并使用远程磁盘 |

其中，核心演示流程只在 Linux 上进行，Windows 上会简单补充说明相关软件的使用方法。同时为了演示方便，两台 Linux 系统统一使用 root 用户登录。

---

## 实操目标

这次要完成的事情很明确：

1. 在 `192.168.1.115` 上安装并配置 iSCSI Target。
2. 在 Target 上创建一个 10G 的 fileio LUN。
3. 在 `192.168.1.135` 上配置 iSCSI Initiator。
4. Initiator 发现并登录 Target。
5. Initiator 上出现一块新的 `/dev/sdb` 磁盘。
6. 对新磁盘分区、格式化、挂载并写入测试文件。
7. 配置开机自动登录和自动挂载。
8. 重启 Initiator 验证配置是否仍然生效。

---

## 确认两台机器的基础环境

先看 Target，也就是 `192.168.1.115`：

```bash
[root@target ~]# hostname
dev-alma

[root@target ~]# cat /etc/os-release | sed -n '1,6p'
NAME="AlmaLinux"
VERSION="10.1 (Heliotrope Lion)"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="10.1"
PLATFORM_ID="platform:el10"

[root@target ~]# ip -br addr
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens18            UP             192.168.1.115/24 ...

[root@target ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
NAME                 SIZE TYPE FSTYPE      MOUNTPOINTS
sda                  500G disk
├─sda1                 1M part
├─sda2                 1G part xfs         /boot
└─sda3               499G part LVM2_member
  ├─almalinux-root    70G lvm  xfs         /
  ├─almalinux-swap   7.9G lvm  swap        [SWAP]
  └─almalinux-home 421.1G lvm  xfs         /home
```

再看 Initiator，也就是 `192.168.1.135`：

```bash
[root@initiator ~]# hostname
dev-alma

[root@initiator ~]# cat /etc/os-release | sed -n '1,6p'
NAME="AlmaLinux"
VERSION="10.1 (Heliotrope Lion)"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="10.1"
PLATFORM_ID="platform:el10"

[root@initiator ~]# ip -br addr
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens18            UP             192.168.1.135/24 ...

[root@initiator ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
NAME                 SIZE TYPE FSTYPE      MOUNTPOINTS
sda                  500G disk
├─sda1                 1M part
├─sda2                 1G part xfs         /boot
└─sda3               499G part LVM2_member
  ├─almalinux-root    70G lvm  xfs         /
  ├─almalinux-swap   7.9G lvm  swap        [SWAP]
  └─almalinux-home 421.1G lvm  xfs         /home
```

开始前，两台机器都只有系统盘 `sda`。如果后面 iSCSI 配置成功，Initiator 上应该多出一块来自 Target 的 `sdb`。

---

## 安装 Target 工具

在 Target 上安装 `targetcli`：

```bash
[root@target ~]# dnf install -y targetcli iscsi-initiator-utils
Last metadata expiration check: 0:10:23 ago on Mon 15 Jun 2026 11:08:05 PM CST.
Package iscsi-initiator-utils-6.2.1.11-0.git4b3e853.el10.x86_64 is already installed.
Dependencies resolved.
...
Installed:
  targetcli-2.1.58-5.el10.noarch
  target-restore-2.1.76-12.el10.noarch
  python3-rtslib-2.1.76-12.el10.noarch
...
Complete!

[root@target ~]# rpm -q targetcli iscsi-initiator-utils
targetcli-2.1.58-5.el10.noarch
iscsi-initiator-utils-6.2.1.11-0.git4b3e853.el10.x86_64
```

虽然这台机器主要作为 Target，但安装 `iscsi-initiator-utils` 也没坏处，里面有一些 iSCSI 相关工具。

此时 Target 配置还是空的：

```bash
[root@target ~]# targetcli ls
o- /
  o- backstores
  | o- block   [Storage Objects: 0]
  | o- fileio  [Storage Objects: 0]
  | o- pscsi   [Storage Objects: 0]
  | o- ramdisk [Storage Objects: 0]
  o- iscsi     [Targets: 0]
  o- loopback  [Targets: 0]
```

---

## 准备 Initiator IQN

在 Initiator 上确认 `iscsi-initiator-utils`：

```bash
[root@initiator ~]# dnf install -y iscsi-initiator-utils
Last metadata expiration check: 0:19:08 ago on Mon 15 Jun 2026 10:59:21 PM CST.
Package iscsi-initiator-utils-6.2.1.11-0.git4b3e853.el10.x86_64 is already installed.
Dependencies resolved.
Nothing to do.
Complete!

[root@initiator ~]# rpm -q iscsi-initiator-utils
iscsi-initiator-utils-6.2.1.11-0.git4b3e853.el10.x86_64
```

这里有一个小细节：很多发行版安装 `iscsi-initiator-utils` 后，会自动生成 `/etc/iscsi/initiatorname.iscsi`。但是有些发行版可能不会自动生成，下文假设该文件不存在以便统一处理。

生成 IQN：

```bash
[root@initiator ~]# iscsi-iname
iqn.1994-05.com.redhat:83441c5b77fa
```

写入配置文件：

```bash
[root@initiator ~]# mkdir -p /etc/iscsi

[root@initiator ~]# echo 'InitiatorName=iqn.1994-05.com.redhat:83441c5b77fa' > /etc/iscsi/initiatorname.iscsi

[root@initiator ~]# cat /etc/iscsi/initiatorname.iscsi
InitiatorName=iqn.1994-05.com.redhat:83441c5b77fa
```

启动 `iscsid`：

```bash
[root@initiator ~]# systemctl enable --now iscsid
Created symlink '/etc/systemd/system/multi-user.target.wants/iscsid.service' → '/usr/lib/systemd/system/iscsid.service'.

[root@initiator ~]# systemctl is-active iscsid
active
```

这个 IQN 后面要添加到 Target 的 ACL 中。否则 Target 即使存在，Initiator 也拿不到对应 LUN。

---

## 创建后端 LUN 文件

本文使用 fileio 方式创建一个 10G 的后端文件。

```bash
[root@target ~]# mkdir -p /var/lib/iscsi-disks

[root@target ~]# truncate -s 10G /var/lib/iscsi-disks/alma135-lun0.img

[root@target ~]# targetcli /backstores/fileio create alma135_lun0 /var/lib/iscsi-disks/alma135-lun0.img 10G
/var/lib/iscsi-disks/alma135-lun0.img exists, using its size (10737418240 bytes) instead
Created fileio alma135_lun0 with size 10737418240
```

这里的 `alma135_lun0` 是 Target 端看到的后端存储对象名。它背后对应的真实文件是：

```text
/var/lib/iscsi-disks/alma135-lun0.img
```

---

## 创建 Target、LUN 和 ACL

创建 Target IQN：

```bash
[root@target ~]# targetcli /iscsi create iqn.2026-06.lab.local:alma-target01
Created target iqn.2026-06.lab.local:alma-target01.
Created TPG 1.
Global pref auto_add_default_portal=true
Created default portal listening on all IPs (0.0.0.0), port 3260.
```

把后端 fileio 对象映射成 LUN：

```bash
[root@target ~]# targetcli /iscsi/iqn.2026-06.lab.local:alma-target01/tpg1/luns create /backstores/fileio/alma135_lun0
Created LUN 0.
```

添加 Initiator ACL：

```bash
[root@target ~]# targetcli /iscsi/iqn.2026-06.lab.local:alma-target01/tpg1/acls create iqn.1994-05.com.redhat:83441c5b77fa
Created Node ACL for iqn.1994-05.com.redhat:83441c5b77fa
Created mapped LUN 0.
```

保存配置：

```bash
[root@target ~]# targetcli saveconfig
Configuration saved to /etc/target/saveconfig.json
```

开放 iSCSI 默认端口：

```bash
[root@target ~]# firewall-cmd --permanent --add-port=3260/tcp
success

[root@target ~]# firewall-cmd --reload
success
```

启动并设置 Target 服务开机自启：

```bash
[root@target ~]# systemctl enable --now target
Created symlink '/etc/systemd/system/multi-user.target.wants/target.service' → '/usr/lib/systemd/system/target.service'.
```

确认 `3260` 已监听：

```bash
[root@target ~]# ss -lntp | grep 3260
LISTEN 0      256          0.0.0.0:3260      0.0.0.0:*
```

---

## 查看 Target 配置

在 Target 上查看最终配置：

```bash
[root@target ~]# targetcli ls
o- /
  o- backstores
  | o- fileio [Storage Objects: 1]
  |   o- alma135_lun0 [/var/lib/iscsi-disks/alma135-lun0.img (10.0GiB) write-back activated]
  o- iscsi [Targets: 1]
    o- iqn.2026-06.lab.local:alma-target01 [TPGs: 1]
      o- tpg1 [no-gen-acls, no-auth]
        o- acls [ACLs: 1]
        | o- iqn.1994-05.com.redhat:83441c5b77fa [Mapped LUNs: 1]
        |   o- mapped_lun0 [lun0 fileio/alma135_lun0 (rw)]
        o- luns [LUNs: 1]
        | o- lun0 [fileio/alma135_lun0 (/var/lib/iscsi-disks/alma135-lun0.img)]
        o- portals [Portals: 1]
          o- 0.0.0.0:3260 [OK]
```

注意这里显示的是：

```text
[no-auth]
```

也就是说本文先不启用 CHAP，靠内网、端口、防火墙和 ACL 跑通基本流程。生产环境建议再加 CHAP 和更严格的网络隔离。

---

## 发现 Target

回到 Initiator，登录前先看一下磁盘，此时还只有系统盘：

```bash
[root@initiator ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
NAME                 SIZE TYPE FSTYPE      MOUNTPOINTS
sda                  500G disk
├─sda1                 1M part
├─sda2                 1G part xfs         /boot
└─sda3               499G part LVM2_member
  ├─almalinux-root    70G lvm  xfs         /
  ├─almalinux-swap   7.9G lvm  swap        [SWAP]
  └─almalinux-home 421.1G lvm  xfs         /home
```

发现 Target：

```bash
[root@initiator ~]# iscsiadm -m discovery -t sendtargets -p 192.168.1.115
192.168.1.115:3260,1 iqn.2026-06.lab.local:alma-target01
```

这说明 Initiator 已经能从 Target 上发现可用目标。

---

## 登录 Target

执行登录：

```bash
[root@initiator ~]# iscsiadm -m node -T iqn.2026-06.lab.local:alma-target01 -p 192.168.1.115:3260 --login
Login to [iface: default, target: iqn.2026-06.lab.local:alma-target01, portal: 192.168.1.115,3260] successful.
```

查看 iSCSI session：

```bash
[root@initiator ~]# iscsiadm -m session -P 1
Target: iqn.2026-06.lab.local:alma-target01 (non-flash)
    Current Portal: 192.168.1.115:3260,1
    Persistent Portal: 192.168.1.115:3260,1
        Iface Initiatorname: iqn.1994-05.com.redhat:83441c5b77fa
        Iface IPaddress: 192.168.1.135
        iSCSI Connection State: LOGGED IN
        iSCSI Session State: LOGGED_IN
```

再看磁盘：

```bash
[root@initiator ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL
NAME                 SIZE TYPE FSTYPE      MOUNTPOINTS MODEL
sda                  500G disk                         QEMU HARDDISK
├─sda1                 1M part
├─sda2                 1G part xfs         /boot
└─sda3               499G part LVM2_member
  ├─almalinux-root    70G lvm  xfs         /
  ├─almalinux-swap   7.9G lvm  swap        [SWAP]
  └─almalinux-home 421.1G lvm  xfs         /home
sdb                   10G disk                         alma135_lun0
```

`sdb` 就是从 `192.168.1.115` 这台 Target 暴露过来的远程 LUN。

---

## 分区、格式化和挂载

接下来把 `/dev/sdb` 当普通磁盘处理。

```bash
[root@initiator ~]# parted -s /dev/sdb mklabel gpt mkpart primary xfs 1MiB 100%
Warning: The resulting partition is not properly aligned for best performance: 2048s % 16384s != 0s

[root@initiator ~]# mkfs.xfs -f /dev/sdb1
meta-data=/dev/sdb1              isize=512    agcount=4, agsize=655295 blks
         =                       sectsz=512   attr=2, projid32bit=1
         =                       crc=1        finobt=1, sparse=1, rmapbt=1
data     =                       bsize=4096   blocks=2621179, imaxpct=25
log      =internal log           bsize=4096   blocks=16384, version=2
realtime =none                   extsz=4096   blocks=0, rtextents=0

[root@initiator ~]# mkdir -p /mnt/iscsi-lun0

[root@initiator ~]# mount /dev/sdb1 /mnt/iscsi-lun0

[root@initiator ~]# echo "hello-from-remote-host-$(hostname)-$(date -Is)" > /mnt/iscsi-lun0/hello-iscsi.txt

[root@initiator ~]# sync
```

查看结果：

```bash
[root@initiator ~]# df -hT /mnt/iscsi-lun0
Filesystem     Type  Size  Used Avail Use% Mounted on
/dev/sdb1      xfs    10G  228M  9.8G   3% /mnt/iscsi-lun0

[root@initiator ~]# cat /mnt/iscsi-lun0/hello-iscsi.txt
hello-from-remote-host-dev-alma-2026-06-15T23:21:36+08:00

[root@initiator ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL /dev/sdb
NAME   SIZE TYPE FSTYPE MOUNTPOINTS     MODEL
sdb     10G disk                        alma135_lun0
└─sdb1  10G part xfs    /mnt/iscsi-lun0
```

到这里，远程 LUN 已经变成了 Initiator 上可正常读写的文件系统。

---

## 配置自动登录和自动挂载

先把 iSCSI node 设置成自动登录：

```bash
[root@initiator ~]# iscsiadm -m node -T iqn.2026-06.lab.local:alma-target01 -p 192.168.1.115:3260 --op update -n node.startup -v automatic
```

启用服务：

```bash
[root@initiator ~]# systemctl enable --now iscsi iscsid
```

查看 `/dev/sdb1` 的 UUID：

```bash
[root@initiator ~]# blkid /dev/sdb1
/dev/sdb1: UUID="52dcb0a3-f704-41fe-912e-e76f099ce9aa" BLOCK_SIZE="512" TYPE="xfs" PARTLABEL="primary" PARTUUID="c7c86cd4-ed71-49bb-b9a8-47705bf8397a"
```

写入 `/etc/fstab`：

```bash
[root@initiator ~]# echo 'UUID=52dcb0a3-f704-41fe-912e-e76f099ce9aa /mnt/iscsi-lun0 xfs _netdev,nofail 0 0' >> /etc/fstab

[root@initiator ~]# tail -n 4 /etc/fstab
UUID=0366374e-5ceb-4a68-96ff-7e15cb4e2218 /boot                   xfs     defaults        0 0
UUID=7accc315-e857-43af-8af5-0d7001eb480c /home                   xfs     defaults        0 0
UUID=2a393cd2-9118-4fe9-8192-7e78371e00ba none                    swap    defaults        0 0
UUID=52dcb0a3-f704-41fe-912e-e76f099ce9aa /mnt/iscsi-lun0 xfs _netdev,nofail 0 0
```

这里有两个关键参数：

- `_netdev`：告诉系统这是依赖网络的设备。
- `nofail`：避免网络存储暂时不可用时阻塞开机。

确认 iSCSI node 已经是自动登录：

```bash
[root@initiator ~]# iscsiadm -m node -T iqn.2026-06.lab.local:alma-target01 -p 192.168.1.115:3260 -o show | grep node.startup
node.startup = automatic
```

---

## 重启验证

为了确认配置不是“当前会话里刚好可用”，重启 Initiator：

```bash
[root@initiator ~]# reboot
```

机器回来之后检查 iSCSI session：

```bash
[root@initiator ~]# iscsiadm -m session -P 1
Target: iqn.2026-06.lab.local:alma-target01 (non-flash)
    Current Portal: 192.168.1.115:3260,1
    Iface Initiatorname: iqn.1994-05.com.redhat:83441c5b77fa
    Iface IPaddress: 192.168.1.135
    iSCSI Connection State: LOGGED IN
    iSCSI Session State: LOGGED_IN
```

查看磁盘、挂载点和测试文件：

```bash
[root@initiator ~]# lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL
NAME                 SIZE TYPE FSTYPE      MOUNTPOINTS     MODEL
sda                  500G disk                             QEMU HARDDISK
├─sda1                 1M part
├─sda2                 1G part xfs         /boot
└─sda3               499G part LVM2_member
  ├─almalinux-root    70G lvm  xfs         /
  ├─almalinux-swap   7.9G lvm  swap        [SWAP]
  └─almalinux-home 421.1G lvm  xfs         /home
sdb                   10G disk                             alma135_lun0
└─sdb1                10G part xfs         /mnt/iscsi-lun0

[root@initiator ~]# findmnt /mnt/iscsi-lun0
TARGET          SOURCE    FSTYPE OPTIONS
/mnt/iscsi-lun0 /dev/sdb1 xfs    rw,relatime,seclabel,attr2,inode64,logbufs=8,logbsize=32k,noquota

[root@initiator ~]# cat /mnt/iscsi-lun0/hello-iscsi.txt
hello-from-remote-host-dev-alma-2026-06-15T23:21:36+08:00
```

这说明重启后：

- iSCSI session 自动恢复。
- `/dev/sdb` 自动出现。
- `/dev/sdb1` 自动挂载到 `/mnt/iscsi-lun0`。
- 原来写入的测试文件仍然可以读取。

---

## 回到 Target 验证后端

在 Target 上看后端文件实际占用：

```bash
[root@target ~]# du -h /var/lib/iscsi-disks/alma135-lun0.img
65M /var/lib/iscsi-disks/alma135-lun0.img
```

虽然这个 LUN 逻辑上是 10G，但因为是 `truncate` 创建的稀疏文件，刚开始只占用了几十 MB。随着 Initiator 写入数据，它会逐渐占用更多真实磁盘空间。

再看 Target ACL：

```bash
[root@target ~]# targetcli ls /iscsi/iqn.2026-06.lab.local:alma-target01/tpg1/acls
o- acls [ACLs: 1]
  o- iqn.1994-05.com.redhat:83441c5b77fa [Mapped LUNs: 1]
    o- mapped_lun0 [lun0 fileio/alma135_lun0 (rw)]
```

Target 服务日志里也能看到配置恢复：

```bash
[root@target ~]# journalctl -u target --no-pager -n 10
Jun 15 23:19:50 dev-alma systemd[1]: Starting target.service - Restore LIO kernel target configuration...
Jun 15 23:19:51 dev-alma systemd[1]: Finished target.service - Restore LIO kernel target configuration.
```

---

## 这次实操的完整链路

最终链路是这样：

![AlmaLinux iSCSI 实操完整链路](iscsi-almalinux-complete-chain.svg)

从 Initiator 看，它只是在操作一块普通磁盘：

```text
/dev/sdb
└─/dev/sdb1
  └─/mnt/iscsi-lun0
```

但从物理位置看，这块盘的后端文件其实在 Target：

```text
192.168.1.115:/var/lib/iscsi-disks/alma135-lun0.img
```

这就是 iSCSI 最核心的体验：**远程存储，以本地块设备的形式出现在客户端。**

---

## Windows 10 连接 iSCSI Target

1. Win + R 输入 `iscsicpl` 打开 iSCSI 发起程序，首次运行会提示你需要先开启 MSiSCSI 服务，点击“是”：

![开启 MSiSCSI 服务](win-iscsi-servcie-need-open.png)

2. Win + R 输入 `services.msc` 打开服务管理器，找到 MSiSCSI 服务，确保它已启动并设置为自动启动：

![MSiSCSI 服务](win-iscsi-servcie-start.png)

3. 在 iSCSI 发起程序里，点击“配置”标签页，拿到 Initiator 的 IQN，并加入到 Target ACL 里（加入 ACL 流程参考上文）：

![iSCSI 配置](win-iscsi-iqn.png)

4. 回到“发现”标签页，点击下方的“发现门户”按钮，填入 Target 的 IP 地址后点击“确认”：

![iSCSI 发现](win-iscsi-discover.png)

5. 发现成功后会自动出现已发现的门户和对应的 Target:

![iSCSI 发现门户](win-iscsi-discover-port.png)
![iSCSI 发现目标](win-iscsi-discover-target.png)

6. Win + R 输入 `diskmgmt.msc` 打开磁盘管理，先看下当前系统的磁盘：

![磁盘管理](win-sys-disks1.png)

7. 回到在发起程序的“目标”标签页，点击下方的“连接”按钮，连接到 Target：

![iSCSI 连接](win-iscsi-conn-target.png)

其中“收藏”复选框用于确保系统重启时能够自动连接到 Target。

8. 再次确认系统磁盘情况：

![磁盘管理](win-sys-disks2.png)

可以看到系统上多了一块新磁盘：“磁盘1”，大小为 10GB，很显然这是从 Target 连接过来的 LUN。可以查看磁盘属性进一步确认：

![磁盘属性](win-sys-disks-props.png)

以上步骤完整展示了 Windows 10 连接 iSCSI Target 的流程。由于“磁盘1”正被 Linux 的 Initiator 使用且上面存在 Windows 不识别的 xfs 文件系统，所以 Windows 10 无法直接挂载它。当然，你依然可以格式化“磁盘1”并创建 NTFS 文件系统的卷，只不过这就是前文提到的多节点同时使用一个 LUN 的场景，在没有集群文件系统的加持下是会导致数据损坏，这里就不再演示。

## 总结

这次实操把 iSCSI 从“概念”落到了真实机器上。

在 Target 端，我们用 AlmaLinux 10.1 的 `targetcli` 创建了一个 fileio backing store，把 `/var/lib/iscsi-disks/alma135-lun0.img` 暴露成一个 10G LUN，并通过 ACL 只授权指定 Initiator IQN 访问。最终 Target 监听在 `3260/tcp`，对外提供 `iqn.2026-06.lab.local:alma-target01`。

在 Linux Initiator 端，我们用 `iscsiadm` 完成 discovery 和 login。登录成功后，系统里出现了新的 `/dev/sdb`，然后像普通本地磁盘一样完成了分区、格式化、挂载和读写测试。重启之后，`node.startup = automatic` 和 `/etc/fstab` 中的 `_netdev,nofail` 也验证了自动登录和自动挂载可以正常恢复。

Windows 10 的图形化流程也证明了同一个 Target 可以被 Windows 发起程序发现和连接。不过这次没有让 Windows 格式化或写入这个 LUN，因为它已经被 Linux 格式化成 XFS 并挂载使用。普通 XFS、NTFS、ext4 这类文件系统都不是给多主机同时写同一块块设备设计的，强行这么做很容易破坏文件系统。

所以，iSCSI 的关键不是“远程盘可以给很多机器随便共用”，而是：

- Target 负责提供远程块设备。
- Initiator 负责发现、登录和使用这个块设备。
- 客户端系统看到的是磁盘，不是远程文件夹。
- 一个普通 LUN 通常应该只给一个普通主机独占写入。
- 如果要多主机共享写入，需要集群文件系统、虚拟化平台存储机制或专门的上层协调能力。

到这里，这条链路已经完整跑通：

```text
Target fileio LUN -> iSCSI/TCP 3260 -> Initiator /dev/sdb -> 文件系统 -> 挂载点
```
