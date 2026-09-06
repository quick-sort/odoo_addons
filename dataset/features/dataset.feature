# language: zh-CN
功能: 数据集管理设计约束

  场景: data_chunk.key 由 dataset 自动安全生成
    假设 dataset 的 key_fields=["split", "shard"]
    当 metadata={"split": "train", "shard": "001"}
    那么 key 应为 "source/dataset/train/001.csv"

  场景: chunk key 路径组件必须明确且安全
    当 source、dataset、key field 或 metadata 值为空、缺失、为 "."、".."、包含斜杠或反斜杠
    那么 系统应抛出清晰的验证错误

  场景: dataset.data_chunk 在同 dataset_id 下 key 必须唯一
    那么 系统应拒绝同一数据集中的重复 key
