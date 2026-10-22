FROM node:22-slim
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY dashboard/package.json dashboard/package.json
COPY widget/package.json widget/package.json
RUN pnpm install --frozen-lockfile
COPY dashboard/ dashboard/
COPY widget/src/client.ts widget/src/client.ts
WORKDIR /workspace/dashboard
CMD ["pnpm", "dev"]
