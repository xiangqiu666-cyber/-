# 部署到 PythonAnywhere（电脑端操作，一步一步来）

## ⚠️ 先读这一段：免费账户抓不了 500.com

PythonAnywhere 的**免费（Beginner）账户限制出站网络**，只能访问官方白名单里的网站
（GitHub、PyPI、Google 之类），而 **500.com 不在白名单内**——部署上去后所有抓取会失败。

- **免费账户**：只能当"壳子"跑，看不到数据 → 不要选
- **付费账户（Hacker，$5/月起）**：解除网络限制，可正常抓取 → 这个才行
- **如果不想花钱**：改用 Render（免费、可任意联网，缺点是 15 分钟无访问会休眠，下次打开要等约 1 分钟）。Render 的用法见本文末尾

另外免费账户磁盘只有 **512MB**，而赔率页缓存会长年累积（我已在程序里加了自动清理，
上限约 90MB / 260 个文件，可长期跑）。

---

## 一、准备工作（在电脑上）

1. 本压缩包解压后得到一个文件夹 **`divergence`**（已用英文名，避免服务器上处理中文路径出错）
2. 文件夹里应该有以下文件：
   - `server.py`（后端主程序）
   - `index.html`（手机页面）
   - `requirements.txt`（依赖）
   - `pythonanywhere_wsgi.py`（PythonAnywhere 入口）
   - `.cache/hist_*.json`（已积累的 411 场战绩库数据，建议一起传，战绩库开箱就有内容）

## 二、上传文件

1. 打开 https://www.pythonanywhere.com/ 登录
2. 顶部选 **Files** 页签
3. 在 "Upload a file" 那里选本压缩包 **整个上传**（文件名 `分歧指数-PythonAnywhere.zip`），点 Upload
4. 上传完后，开一个 Bash 命令行（Consoles → Bash），执行解压：

```bash
cd ~
unzip 分歧指数-PythonAnywhere.zip
ls ~/divergence
```

看到 `server.py`、`index.html` 就说明成功了。

> 如果中文 zip 名字解压有问题，就在电脑上先把压缩包改名为 `app.zip` 再传，上面命令相应改成 `unzip app.zip`。
>
> 记下你的**用户名**：页面右上角显示的就是，后面要用到。

## 三、安装依赖

1. 顶部选 **Consoles** → 点 **Bash** 开一个命令行
2. 逐行执行（每行回车，等它跑完再下一行）：

```bash
cd ~/divergence
pip install --user -r requirements.txt
```

PythonAnywhere 通常已预装 flask 和 requests，如果提示已存在就不用管。

## 四、创建 Web 应用

1. 顶部选 **Web** 页签
2. 点 **Add a new web app** → 一路 Next → 到最后一屏选 **Manual configuration**
   （**不要**选 Flask 自动模板，我们自己指定入口）
3. Python 版本选 **3.11**（或 3.10，都能跑）
4. 创建完成后，页面往下拉，找到 **Code** 区块

## 五、配置 WSGI（最关键的一步）

在 **Code** 区块里点 **WSGI configuration file** 那个长链接，打开后
**删掉里面全部内容**，换成 `pythonanywhere_wsgi.py` 的内容，并把第一行的用户名改成你自己的：

```python
USERNAME = "这里改成你的用户名"
```

例如你的用户名是 `zhangsan`，就写 `USERNAME = "zhangsan"`。

改完点 **Save**。

再回到 Web 页签，**Code** 区块确认：
- **Source code**: `/home/你的用户名/divergence`
- **Working directory**: `/home/你的用户名/divergence`

## 六、启动

回到 **Web** 页签顶部，点绿色大按钮 **Reload 你的用户名.pythonanywhere.com**

然后浏览器打开：
```
https://你的用户名.pythonanywhere.com
```
（免费账户只能用这个域名，付费账户可以绑自己的域名）

手机浏览器打开同一个地址即可，建议"添加到主屏幕"当 App 用。

---

## 常见问题

**打不开 / 500 错误**
点 Web 页签的 **Error log** 链接看报错。最常见两个原因：
1. WSGI 里用户名没改（还是"你的用户名"）→ 路径不对
2. 依赖没装 → 回第三步重新 `pip install --user -r requirements.txt`

**页面能开，但一直显示"抓取失败"**
就是开头说的问题：免费账户访问不了 500.com。换成付费账户，或改用 Render。

**战绩库是空的**
说明 `.cache/hist_*.json` 没传上去，或路径不对。开箱应该能看到"27 天 411 场"。
没有也没关系，每天点"复盘"会自动积累。

**免费账户每月要续期**
PythonAnywhere 免费 web app 大约每月需要在 Web 页签点一次延期（页面会有黄色提示条，点一下即可）。

**磁盘满了**
程序已自动清理页面缓存（上限约 90MB）。如果还满，在 Bash 里执行 `rm -f ~/divergence/.cache/*.html` 清空缓存（不影响战绩库数据）。

---

## 附：改用 Render（免费、可联网，推荐不想花钱时选）

Render 免费版能正常访问 500.com，缺点是 15 分钟没人访问会休眠，下次打开要等约 1 分钟。

1. 把 `divergence` 文件夹传到 GitHub（新建仓库，上传文件）
2. 打开 https://render.com/ → New → Web Service → 连上刚才的仓库
3. 配置：
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
   - （仓库里的 `Procfile` 写好了这条命令，Render 也能自动识别）
4. 点 Create，部署完成后会给你一个 `https://xxx.onrender.com` 的地址

> 注意：Render 免费版重启会清空文件，战绩库数据会丢（页面缓存也会）。
> 想长期积累战绩，还是用 PythonAnywhere 付费账户或自己的机器。
