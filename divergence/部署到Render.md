# 部署到 Render（免费、可正常抓取 500.com）

全程在网页上操作，不用在自己电脑上装任何东西。
总耗时大约 15 分钟，主要花在注册账号上。

---

## 第 1 步：注册 GitHub（用来放代码，免费）

Render 是从 GitHub 拿代码的，所以先要有 GitHub 账号。

1. 打开 https://github.com/signup
2. 填邮箱、密码、用户名（用户名随便起，比如 `fqzs-app`，后面要用）
3. 邮箱里收个验证码，验证一下就注册好了

## 第 2 步：新建一个仓库（Repository）

1. 登录后打开 https://github.com/new
2. **Repository name** 填 `fqzs`
3. 选 **Public**（公开）
4. 勾选 **Add a README file**（这样仓库不是空的，后面上传更顺）
5. 点绿色按钮 **Create repository**

## 第 3 步：把文件上传到这个仓库

进入刚建的仓库页面，你会看到文件列表（只有 README.md）。

1. 点右边的 **Add file** → **Upload files**
2. 打开我给你的压缩包，把 **`divergence` 文件夹里的这些东西**拖进上传框：

   - `server.py`
   - `index.html`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
   - `README.md`
   - **`history` 文件夹里的 `all.json`**（就 **1 个文件**，里面是已积累的 411 场战绩库，传上去战绩库开箱就有内容）

   ⚠️ **不要传 `.cache` 文件夹**（里面是几百 MB 的网页缓存，传上去会拖慢部署，而且没用）

3. 拖完后页面下方会有文件列表，确认有这 **10 个文件**：

   ```
   server.py   index.html   requirements.txt   Procfile   runtime.txt
   README.md   部署到Render.md   部署到PythonAnywhere.md   pythonanywhere_wsgi.py
   history/all.json
   ```

4. 点绿色 **Commit changes**

> 如果拖文件夹没反应：点 **Add file → Create new file**，
> 文件名框里直接输入 `history/all.json`，再把文件内容粘贴进去，也能自动建目录。

## 第 4 步：注册 Render

1. 打开 https://render.com/
2. 点 **Get Started**，选 **Sign in with GitHub**（用 GitHub 登录最省事，不用再填一遍资料）
3. 会弹出授权页面，点 **Authorize Render**

## 第 5 步：创建网站

1. 登录后进 Dashboard，点右上角 **New +** → 选 **Web Service**
2. 页面会列出你的 GitHub 仓库，**找到 `fqzs` 点右边的 Connect**
   - 如果列表里没有：点下面的 "Configure account"，授权 Render 访问这个仓库
3. 接下来填这些（**其他全部留默认**）：

| 项目 | 填什么 |
|---|---|
| **Name** | `fqzs`（随便，会变成网址的一部分） |
| **Region** | **Singapore**（新加坡，离国内最近，最快） |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 180` |
| **Instance Type** | **Free** |

> Start Command 也可以留空，Render 会自动读仓库里的 `Procfile`（我已经写好了同样的命令）。

4. 往下拉，点 **Create Web Service**

## 第 6 步：等它部署完（约 2-3 分钟）

页面会跳到部署详情页，黑色的日志窗口会滚动：

- 看到 `Building...` → 在装依赖
- 看到 `Build successful` → 装好了
- 看到 `Deploying...` → 在启动
- 看到 **`Your service is live`** → 成功了！

网址在页面左上角，形如：
```
https://fqzs-xxxx.onrender.com
```

点开它，就能看到「分歧指数」页面了。

## 第 7 步：手机上用

手机浏览器打开上面那个网址，然后：

- **iPhone**：Safari 底部「分享」按钮 → 添加到主屏幕
- **安卓**：Chrome 右上角菜单 → 添加到主屏幕

之后从桌面图标打开，就跟 App 一样。

---

## 你一定会遇到的 3 件事（正常现象，不是坏了）

**1. 第一次打开要等 40-60 秒**
Render 免费版 15 分钟没人访问就会"睡觉"，下次打开要重新唤醒。
等它醒过来之后就正常了，白天频繁用的话基本感觉不到。

**2. 战绩库的新数据可能会丢**
免费版重启会清空磁盘。我已经做了处理：
- 仓库里的 `history/` 是**固定的基线**（411 场），每次部署都会带上，所以战绩库永远不会是空的
- 你新跑的复盘数据存在磁盘上，**重启后会丢**

想让新数据也不丢，有两个办法：
- 花 3 分钟开个免费的 Redis（见下面"进阶"），一劳永逸
- 或者接受它，每天想起来点一次「复盘」重新积累

**3. 每天要手动点一次「复盘」**
战绩库靠跑复盘来积累。当天比赛结束后，在页面上点「复盘」按钮，那天的数据就进库了。

---

## 常见问题

**Build failed（构建失败）**
点日志看红色报错。最常见是 `requirements.txt` 没传上去 → 回第 3 步确认文件在仓库里。

**Service 起来了但打不开 / 一直转圈**
等 1 分钟再试（在唤醒）。如果超过 3 分钟还是不行，看日志里有没有 `Error` 或 `Failed to bind`。

**页面能开，但显示"抓取失败"**
极少数情况下 Render 的 IP 被 500 临时限制。等一会儿再试，或点页面上的「抓取」重试。

**时区不对（凌晨的比赛算到前一天）**
代码里已默认按北京时间（UTC+8）算。如果你手贱改过环境变量 `TZ_OFFSET`，把它设成 `8`。

**想改代码**
直接在 GitHub 网页上改文件 → Commit → Render 会自动重新部署（约 2 分钟）。

---

## 进阶（可选）：开个免费 Redis，战绩永不丢失

1. Render Dashboard → **New +** → **Key Value**（Redis）
2. Name 填 `fqzs-kv`，Region 选 **Singapore**，Instance Type 选 **Free**
3. 创建好后，复制它的 **Internal Redis URL**（形如 `redis://red-xxxx:6379`）
4. 回到你的 Web Service 页面 → 左边 **Environment** → 点 **Add Environment Variable**
   - Key：`REDIS_URL`
   - Value：刚才复制的那串 URL
5. 保存后 Render 会自动重新部署

代码里已经写好了：检测到 `REDIS_URL` 就自动把战绩库存到 Redis，重启不丢。
没配置就自动用磁盘，不会报错。

> Render 免费 Redis 容量 256MB，存几十万场比赛的记录都够用。
