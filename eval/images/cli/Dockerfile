# baseline 的沙箱镜像：执行层沙箱的基础镜像（python:3.12-slim，与 full 里 bases.basic 相同）加上 CLI。
# 两臂的工具集因此只差在 CLI 本身：模型在 baseline 里能用的命令，与 full 里经 exec 能用的一样。
#   docker build -t paoding-cli eval/images/cli
#   docker build -t paoding-cli --build-arg CLAUDE_CODE_VERSION=<版本> eval/images/cli   # 建议钉成 full 所用 CLI 的版本（claude --version）
# 若 full 的栈配置把 bases.basic 换成了别的镜像，这里的第二个 FROM 要跟着换，否则对照不对等。
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim
ARG CLAUDE_CODE_VERSION=latest
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && claude --version
