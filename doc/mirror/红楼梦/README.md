# 紅樓夢 版本镜像项目

> **迁移说明（2026-10，overview 拆空 GUJI-361）**：本项目记录原在 overview `项目进展/古籍目录/资源镜像/红楼梦/`，迁入 bookget-py `doc/mirror/`（本仓含 IA 上传三件套 `ia_upload.py`/`ia_metadata.py`，与镜像流程同属一脉）。记录为 2026-05-15 的历史执行记录，manifest.json 为当时的 manifest（含 IA identifier、百度网盘目录结构）；百度分享链接即已写入 book-index 各 Book.resources 的公开 mirror 资源，非新增暴露。


> Work ID: `d59df01avcw0`
> 主 manifest: [manifest.json](manifest.json)
> 工作目录（产物）: `D:/tmp/hongloumeng/`
> 流程 skill: `/mirror-to-archive`（原在 overview `.claude/skills/mirror-to-archive/`，随 overview 拆空另行迁移，此处原相对链接已失效）
> 启动日期: 2026-05-15

## 项目目标

把 23 部紅樓夢主版本 Book 中**仅有天一生水原始 URL**的 11 部，做 IA + 百度网盘双备份，并通过 `group` 字段把同源资源绑成一组。

## 范围

| 状态 | 数量 | 说明 |
|---|---|---|
| ✅ 本次处理 | 11 | 仅天一生水的脂评/过渡/程高/翻刻系统主版本 |
| ⏭ 已有 IA | 1 | 甲戌本（彩色影印已有 IA × 2） |
| ⏭ 已有 IA | 1 | 戚寧本（南京图书馆藏戚序本，已上 IA） |
| ⏭ 暂缓 | 4 | 王希廉评 / 萬有文庫 / 蛟川评 / 妙复轩评（HathiTrust / NCL 已可达，下阶段补 IA） |
| ❌ 无资源 | 3 | 靖藏本（已佚）/ 龙云友评（已佚）/ 戚张本（前 40 回未公开影印） |
| ❌ 待补 | 2 | 藤花榭（仅书格 1 处）/ 东观阁（天一生水 1 处，下阶段处理） |

## 11 部清单（本次处理）

| key | edition | book_id | IA identifier | 影印来源 |
|---|---|---|---|---|
| gengchen | 庚辰本 | 96kzirvbwg | hongloumeng-gengchen | 人民文學出版社 1975 |
| jimao | 己卯本 | 96kzj1joqo | hongloumeng-jimao | 上海古籍出版社 1981 |
| mengfu | 蒙府本 | 96kzjkwef4 | hongloumeng-mengfu | 書目文獻出版社 |
| liecang | 列藏本 | 96kzjukr9c | hongloumeng-liecang | 中華書局 1986 |
| jiachen | 甲辰本（夢覺主人序本） | 96kzk3xvk0 | hongloumeng-jiachen | 影印本 |
| chengjia | 程甲本 | 96kzkdm8e8 | hongloumeng-chengjia | 書目文獻出版社 1992 |
| chengyi | 程乙本（倉石本） | 96kzkmzcow | hongloumeng-chengyi-cangshi | 倉石武四郎舊藏影印 |
| jiyou | 己酉本（舒元煒序本） | 96kzkwnpj4 | hongloumeng-jiyou | 首都圖書館藏影印 |
| menggao | 夢稿本（楊繼振藏百廿回紅樓夢稿） | 96kzl60tts | hongloumeng-menggao | 影印本 |
| zhengzang | 鄭藏本 | 96kzlfp6o0 | hongloumeng-zhengzang | 書目文獻出版社 1991 |
| bianzang | 卞藏本 | 96kzlz1wcg | hongloumeng-bianzang | 北京圖書館出版社 2006 |

## 进度

- [x] 2026-05-15 manifest 起稿；从天一生水批量下载 11 部 PDF
- [x] 2026-05-15 渲染缩略图 + Agent 协助定 crop range
- [x] 2026-05-15 用户 review 调整 3 处（蒙府 23 / 列藏 43 / 程甲 25）
- [x] 2026-05-15 裁剪 11 部 PDF
- [x] 2026-05-15 生成 IA metadata（含影印来源说明）
- [x] 2026-05-15 上传 11 部到 IA（见上表 IA identifier 列）
- [x] 2026-05-15 上传 11 部到百度网盘（OAuth device code + chunked upload）
- [x] 2026-05-15 重组百度结构 `/book-index/<book_id>/<group_key>/<中文文件名>.pdf`
- [x] 2026-05-15 用户分享 `/book-index/` 整目录拿到 short URL + 提取码 `0000`
- [x] 2026-05-15 写回 11 部 Book.resources：IA + 百度 mirror group + jiangyu origin（`update_resources.py --bind-jiangyu`）

## 百度网盘分享

- short URL: `https://pan.baidu.com/s/1BY4Rmk2BUdb5ePBkeQYzkA`
- 提取码: `0000`
- 每部 book 的子目录直链 URL 模式：`<base>?from=init&pwd=0000#list/path=%2Fbook-index%2F<book_id>%2F<group_key>`
- 目录结构：`/book-index/<book_id>/<group_key>/<中文文件名>.pdf`

## IA URL 一览

- 庚辰本: https://archive.org/details/hongloumeng-gengchen
- 己卯本: https://archive.org/details/hongloumeng-jimao
- 蒙府本: https://archive.org/details/hongloumeng-mengfu
- 列藏本: https://archive.org/details/hongloumeng-liecang
- 甲辰本: https://archive.org/details/hongloumeng-jiachen
- 程甲本: https://archive.org/details/hongloumeng-chengjia
- 程乙本（仓石本）: https://archive.org/details/hongloumeng-chengyi-cangshi
- 己酉本: https://archive.org/details/hongloumeng-jiyou
- 夢稿本: https://archive.org/details/hongloumeng-menggao
- 鄭藏本: https://archive.org/details/hongloumeng-zhengzang
- 卞藏本: https://archive.org/details/hongloumeng-bianzang

## 跨版本经验沉淀

1. **天一生水 PDF 都是 Kolistan 打包**：开头有 Kolistan 推荐绿色封面 + 出版社红色封面 + 内封 + 版权页（CIP）+ 现代学者代序/导读，末页是 Kolistan 蓝色水印
2. **庚辰本 / 程甲本** 含冯其庸序，序较长（10+ 页）需精确定位
3. **列藏本 / 蒙府本** 含较长现代研究文 + 目录，古籍正文起点在 p23-43 之间
4. **己酉本** 仅古籍正文 + 印章页，无现代附属
5. **甲辰本 / 夢稿本** 现代附属极少（2-3 页）

下次镜像类似天一生水来源的资源时，可直接套用本次的 crop 经验。
