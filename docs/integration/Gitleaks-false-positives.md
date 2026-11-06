# Gitleaks误报核验

2026-11-06推送整合分支后，Gitleaks v8.30.1报告15项generic-api-key。它们全部位于source-manifest-before.json：扫描器把带有api、secret、key等词的源码路径及其SHA-256字符串识别为凭据。

已对清单中本机170项、GitHub78项共248份源码逐个重新计算SHA-256，全部与清单一致；15个报警行均严格属于“源码路径→64位十六进制SHA-256”的JSON条目，没有服务凭据。

.gitleaksignore仅记录f860b524d64b4dae890482a5a2ce6906286e7660提交内的15个精确commit/file/rule/line指纹。没有忽略整个文件、目录、测试套件或generic-api-key规则；后续提交新增或修改同名文件仍接受扫描。没有关闭CI，没有重写或强推历史。

复核采用与GitHub工作流相同的8.30.1官方发行版，并按官方checksums文件核对下载包SHA-256。完整历史扫描须复验为0项；另用仅在内存生成的合成凭据检验扫描规则仍可触发，不把测试值写入仓库。
