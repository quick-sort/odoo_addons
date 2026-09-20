===================================
 Storage Backend S3 MCP
===================================

``storage_backend_mcp`` 的 S3 bridge：把"原生签名 URL"扩展点在 S3 上兑现，
上传/下载字节**直连 S3**（boto3 presigned URL），不经 Odoo 中转。

工作方式
========

- 组件继承 ``s3.adapter``（``_usage`` 保持 ``amazon_s3``），覆盖
  ``presign_upload/presign_download``，复用其现成的 boto3 client 工厂与凭证。
- 不装本 addon 时 S3 后端照常走中转 controller，一切不变；装上是纯增量。

安装
====

- 依赖：``storage_backend_s3``、``storage_backend_mcp``。
- 无新增 Python 依赖（boto3 随 ``storage_backend_s3`` 已声明）。

详细设计见 ``docs/``。
