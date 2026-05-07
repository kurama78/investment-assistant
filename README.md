# Investment Assistant

一个可本地运行、也可部署到公网的投资研究助手 Web 服务，当前默认使用 `gemini-3-flash-preview`。

## 特性

- 本地无依赖启动模式
- Gemini 模型问答接口
- 组合与个股 Playbook 存储
- 适合 Render 的 Docker 部署配置

## 本地启动

1. 设置环境变量
   `GEMINI_API_KEY=你的key`
2. 启动无依赖本地版
   `python run_local.py`
3. 打开
   `http://localhost:5000`

## 可选：Flask 版

如果你的环境允许安装依赖，也可以：

1. `pip install -r requirements.txt`
2. `python web/app.py`

## 模型

默认模型为 `gemini-3-flash-preview`。
如需覆盖，可设置：

`GEMINI_MODEL=gemini-3-flash-preview`

## Render 部署

这个目录已经包含：

- `Dockerfile`
- `render.yaml`

推荐直接部署到 Render。

### 方式一：Blueprint（最省事）

1. 把项目推到 GitHub
2. 在 Render 中选择 `New +` -> `Blueprint`
3. 选择这个仓库
4. Render 会自动识别 `render.yaml`
5. 在环境变量里填写：
   `GEMINI_API_KEY=你的 key`
6. 部署完成后访问分配的公网域名

### 方式二：手动创建 Web Service

1. `New +` -> `Web Service`
2. 连接 GitHub 仓库
3. Environment 选 `Docker`
4. 设置环境变量：
   `GEMINI_API_KEY=你的 key`
   `GEMINI_MODEL=gemini-3-flash-preview`
   `PORT=5000`
5. Health Check Path 填 `/health`
6. 创建并部署

### 部署后验证

- 打开首页 `/`
- 打开 `/health`
- 返回类似：
  `{"ok": true, "model": "gemini-3-flash-preview"}`

## 环境变量

- `GEMINI_API_KEY`
- `GEMINI_MODEL`，默认 `gemini-3-flash-preview`
- `PORT`，默认 `5000`

## 许可证

MIT

## DeepSeek V4 Pro

Set these environment variables to use DeepSeek V4 Pro instead of the default Gemini model:

```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-pro
```

For Render, add the same variables under Environment Variables. Keep
`LLM_PROVIDER=gemini` or leave it unset to continue using the existing Gemini setup.
