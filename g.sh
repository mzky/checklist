#!/bin/bash

# 配置Git用户身份（替换为你的GitHub信息）
GIT_USER_NAME="mzky"
GIT_USER_EMAIL="mzky@163.com"

# 进入项目目录
cd /mnt/checklist || { echo "错误：无法进入/mnt/checklist目录"; exit 1; }

# 设置仓库级别的用户身份（仅对当前仓库有效）
git config user.name "$GIT_USER_NAME"
git config user.email "$GIT_USER_EMAIL"

# 添加所有更新的文件
git add .

# 检查是否有变更
if ! git diff --cached --quiet; then
    # 提交修改
    git commit -m "Auto update at $(date +'%Y-%m-%d %H:%M:%S')"
    
    # 推送到GitHub
    git push origin main
    echo "文件已成功上传到GitHub"
else
    echo "没有检测到文件变更，无需上传"
fi

