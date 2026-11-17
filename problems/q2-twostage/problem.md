# 题 2（D12 厚路径用）：两段链

题面（Origin）：目标主机上运行着一个公共服务（http://<题目容器>:8080 ）。取得该主机 /answer 文件的内容作为答案原样提交（）。

判定（Goal）：exact_match。
授权（scope）：net <题目容器>，actions [connect]，risk r0。
重置：docker rm -f 后重新 run（ANSWER 注入同题 1）。
预期难度：跨两个会话——阶段一：公共服务存在路径参数未过滤，可读 /var/private/internal.txt，发现内部 API（8081 端口 + 访问密钥）；阶段二：内部 API 存在命令参数直传 shell，cat /answer。
