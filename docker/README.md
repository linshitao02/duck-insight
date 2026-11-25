# Duck Insight 部署

在服务器上安装 Docker 和 Docker Compose 后，于本目录执行：

```bash
cp .env.example .env
docker compose up -d --build
```

浏览器打开 `http://服务器IP:8080`。默认账号 `admin` / `admin123`。

首次构建会安装 PyTorch、XGBoost、LightGBM、CatBoost，镜像较大，需要等待一段时间。

数据库默认是容器里的 SQLite，文件在数据卷 `duck-insight-data` 中，删容器不会丢数据。要用已有 MySQL，编辑 `.env` 后执行 `docker compose up -d`。

常用命令：

```bash
docker compose ps
docker compose logs -f backend
docker compose down
```

`docker compose down` 只停容器。数据卷要加 `-v` 才会删除。
