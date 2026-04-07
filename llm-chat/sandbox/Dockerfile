FROM fullstack-dev:latest

ENV DEBIAN_FRONTEND=noninteractive

# 只装 SSH 服务（Python/Node/Java 已在基础镜像中）
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    tree \
    && rm -rf /var/lib/apt/lists/*

# 创建沙箱工作根目录
RUN mkdir -p /sandbox && chmod 777 /sandbox

# SSH 配置
RUN mkdir -p /var/run/sshd \
    && sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# 设置 root 密码（内网环境，生产建议用 key）
RUN echo "root:sandbox123" | chpasswd

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
