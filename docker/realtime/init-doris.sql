-- Apache Doris 实时数仓初始化脚本
-- 用法：待 FE/BE 均 Alive 后执行
--   mysql -h 127.0.0.1 -P 9030 -u root < docker/realtime/init-doris.sql

CREATE DATABASE IF NOT EXISTS dw_ecommerce;
USE dw_ecommerce;

-- 1. 创建智能问数专用只读账号（请上线前修改密码）
CREATE USER IF NOT EXISTS 'doris_ro'@'%' IDENTIFIED BY 'ChangeMe_DorisRo_2026';
GRANT SELECT_PRIV ON dw_ecommerce.* TO 'doris_ro'@'%';

-- 2. 创建 DWD 实时明细表（Unique Key Merge-on-Write，支持 CDC 幂等更新与删除）
CREATE TABLE IF NOT EXISTS dwd_order_item_rt (
    order_item_id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    order_time DATETIME NOT NULL,
    pay_time DATETIME NULL,
    store_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    channel VARCHAR(32) NOT NULL,
    pay_amount DECIMAL(18, 2) NOT NULL,
    refund_amount DECIMAL(18, 2) NOT NULL DEFAULT "0.00",
    status VARCHAR(32) NOT NULL
)
UNIQUE KEY(order_item_id)
COMMENT '订单明细实时表（MySQL oms_order_item -> Flink CDC -> Kafka -> Doris）'
DISTRIBUTED BY HASH(order_item_id) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_unique_key_merge_on_write" = "true"
);

CREATE TABLE IF NOT EXISTS dwd_refund_record_rt (
    refund_id BIGINT NOT NULL,
    order_item_id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    refund_time DATETIME NOT NULL,
    refund_amount DECIMAL(18, 2) NOT NULL,
    reason VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL
)
UNIQUE KEY(refund_id)
COMMENT '退款记录实时表（MySQL oms_refund_record -> Flink CDC -> Kafka -> Doris）'
DISTRIBUTED BY HASH(refund_id) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_unique_key_merge_on_write" = "true"
);

CREATE TABLE IF NOT EXISTS dwd_shipment_rt (
    id BIGINT NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    carrier VARCHAR(32) NOT NULL,
    tracking_no VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    updated_at DATETIME NOT NULL
)
UNIQUE KEY(id)
COMMENT '物流发货实时表（MySQL oms_shipment -> Flink CDC -> Kafka -> Doris）'
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_unique_key_merge_on_write" = "true"
);

-- 3. 创建 Kafka -> Doris Routine Load（Debezium JSON + 软删除支持）
CREATE ROUTINE LOAD dw_ecommerce.rl_order_item ON dwd_order_item_rt
WITH MERGE
COLUMNS(`order_item_id`, `order_id`, `order_time`, `pay_time`, `store_id`, `category_id`, `channel`, `pay_amount`, `refund_amount`, `status`, op),
PRECEDING FILTER op IS NOT NULL,
DELETE ON op = 'd'
PROPERTIES (
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "5",
    "max_batch_rows" = "200000",
    "max_error_number" = "100",
    "format" = "json",
    "jsonpaths" = '["$.after.order_item_id","$.after.order_id","$.after.order_time","$.after.pay_time","$.after.store_id","$.after.category_id","$.after.channel","$.after.pay_amount","$.after.refund_amount","$.after.status","$.op"]',
    "strip_outer_array" = "false",
    "strict_mode" = "false"
)
FROM KAFKA (
    "kafka_broker_list" = "kafka:9092",
    "kafka_topic" = "cdc_ecommerce_oms_order_item",
    "property.kafka_default_offsets" = "OFFSET_BEGINNING",
    "property.group.id" = "doris_rl_order_item"
);

CREATE ROUTINE LOAD dw_ecommerce.rl_refund_record ON dwd_refund_record_rt
WITH MERGE
COLUMNS(`refund_id`, `order_item_id`, `order_id`, `refund_time`, `refund_amount`, `reason`, `status`, op),
PRECEDING FILTER op IS NOT NULL,
DELETE ON op = 'd'
PROPERTIES (
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "5",
    "max_batch_rows" = "200000",
    "max_error_number" = "100",
    "format" = "json",
    "jsonpaths" = '["$.after.refund_id","$.after.order_item_id","$.after.order_id","$.after.refund_time","$.after.refund_amount","$.after.reason","$.after.status","$.op"]',
    "strip_outer_array" = "false",
    "strict_mode" = "false"
)
FROM KAFKA (
    "kafka_broker_list" = "kafka:9092",
    "kafka_topic" = "cdc_ecommerce_oms_refund_record",
    "property.kafka_default_offsets" = "OFFSET_BEGINNING",
    "property.group.id" = "doris_rl_refund_record"
);

CREATE ROUTINE LOAD dw_ecommerce.rl_shipment ON dwd_shipment_rt
WITH MERGE
COLUMNS(`id`, `order_no`, `carrier`, `tracking_no`, `status`, `updated_at`, op),
PRECEDING FILTER op IS NOT NULL,
DELETE ON op = 'd'
PROPERTIES (
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "5",
    "max_batch_rows" = "200000",
    "max_error_number" = "100",
    "format" = "json",
    "jsonpaths" = '["$.after.id","$.after.order_no","$.after.carrier","$.after.tracking_no","$.after.status","$.after.updated_at","$.op"]',
    "strip_outer_array" = "false",
    "strict_mode" = "false"
)
FROM KAFKA (
    "kafka_broker_list" = "kafka:9092",
    "kafka_topic" = "cdc_ecommerce_oms_shipment",
    "property.kafka_default_offsets" = "OFFSET_BEGINNING",
    "property.group.id" = "doris_rl_shipment"
);
