-- InsightForge 多场景数据分析标品
CREATE DATABASE IF NOT EXISTS `insight_forge`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE `insight_forge`;

CREATE TABLE IF NOT EXISTS `sys_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `password` varchar(255) NOT NULL,
  `nickname` varchar(64) DEFAULT NULL,
  `email` varchar(128) DEFAULT NULL,
  `phone` varchar(32) DEFAULT NULL,
  `role` varchar(32) DEFAULT 'user',
  `avatar` varchar(255) DEFAULT NULL,
  `token` varchar(128) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `sys_scenario` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(64) NOT NULL,
  `name` varchar(128) NOT NULL,
  `description` varchar(512) DEFAULT NULL,
  `icon` varchar(64) DEFAULT 'DataAnalysis',
  `is_default` tinyint DEFAULT 0,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `data_project` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `description` varchar(512) DEFAULT NULL,
  `scenario_code` varchar(64) DEFAULT 'store_sales',
  `cover_color` varchar(32) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `data_source` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `engine` varchar(32) DEFAULT 'mysql',
  `host` varchar(128) NOT NULL,
  `port` int DEFAULT 3306,
  `db_user` varchar(128) DEFAULT NULL,
  `db_password` varchar(255) DEFAULT NULL,
  `database_name` varchar(128) DEFAULT NULL,
  `remark` varchar(512) DEFAULT NULL,
  `extra_json` longtext,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `dataset` (
  `id` int NOT NULL AUTO_INCREMENT,
  `project_id` int DEFAULT NULL,
  `name` varchar(128) NOT NULL,
  `scenario_code` varchar(64) DEFAULT 'store_sales',
  `filename` varchar(255) DEFAULT NULL,
  `file_path` varchar(512) DEFAULT NULL,
  `file_type` varchar(32) DEFAULT NULL,
  `origin_type` varchar(32) DEFAULT 'file' COMMENT 'file=落地快照 mysql_live=每次读源表',
  `source_id` int DEFAULT NULL,
  `source_db` varchar(128) DEFAULT NULL,
  `source_table` varchar(128) DEFAULT NULL,
  `sheet_name` varchar(128) DEFAULT NULL,
  `n_rows` int DEFAULT 0,
  `n_cols` int DEFAULT 0,
  `schema_json` longtext,
  `profile_json` longtext,
  `role_json` longtext,
  `remark` varchar(512) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_scenario` (`scenario_code`),
  KEY `idx_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `dataset_bundle` (
  `id` int NOT NULL AUTO_INCREMENT,
  `project_id` int DEFAULT NULL,
  `name` varchar(128) NOT NULL,
  `scenario_code` varchar(64) DEFAULT 'store_sales',
  `fact_dataset_id` int DEFAULT NULL,
  `dataset_ids_json` text,
  `joins_json` longtext,
  `selected_fields_json` longtext COMMENT '勾选展示字段',
  `materialized_path` varchar(512) DEFAULT NULL,
  `n_rows` int DEFAULT 0,
  `n_cols` int DEFAULT 0,
  `schema_json` longtext,
  `remark` varchar(512) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `clean_rule` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `scenario_code` varchar(64) DEFAULT 'store_sales',
  `description` varchar(512) DEFAULT NULL,
  `steps_json` longtext,
  `is_preset` tinyint DEFAULT 0,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `dataset_binding` (
  `id` int NOT NULL AUTO_INCREMENT,
  `target_type` varchar(32) NOT NULL COMMENT 'dataset|bundle',
  `target_id` int NOT NULL,
  `rule_id` int NOT NULL,
  `name` varchar(128) DEFAULT NULL,
  `snapshot_path` varchar(512) DEFAULT NULL,
  `n_rows` int DEFAULT 0,
  `n_cols` int DEFAULT 0,
  `schema_json` longtext,
  `engine_path` varchar(512) DEFAULT NULL COMMENT 'LabelEncoder/Scaler 等清洗状态',
  `status` varchar(32) DEFAULT 'ready',
  `message` varchar(512) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_target` (`target_type`, `target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `train_job` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `scenario_code` varchar(64) DEFAULT 'store_sales',
  `target_type` varchar(32) DEFAULT 'bundle',
  `target_id` int DEFAULT NULL,
  `rule_id` int DEFAULT NULL,
  `binding_id` int DEFAULT NULL,
  `model_type` varchar(64) NOT NULL,
  `task_type` varchar(32) DEFAULT 'regression',
  `params_json` longtext,
  `feature_cols_json` longtext,
  `target_col` varchar(128) DEFAULT NULL,
  `sample_rows` int DEFAULT 0,
  `test_size` decimal(6,4) DEFAULT 0.20,
  `random_state` int DEFAULT 42,
  `log_target` tinyint DEFAULT 0,
  `status` varchar(32) DEFAULT 'pending',
  `progress` int DEFAULT 0,
  `log_text` longtext,
  `metrics_json` longtext,
  `importance_json` longtext,
  `curves_json` longtext,
  `model_path` varchar(512) DEFAULT NULL,
  `artifact_path` varchar(512) DEFAULT NULL,
  `duration_sec` decimal(12,2) DEFAULT NULL,
  `error_message` text,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `predict_job` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) DEFAULT NULL,
  `train_job_id` int NOT NULL,
  `input_type` varchar(32) DEFAULT 'form',
  `input_json` longtext,
  `input_path` varchar(512) DEFAULT NULL,
  `result_json` longtext,
  `result_path` varchar(512) DEFAULT NULL,
  `use_llm` tinyint DEFAULT 0,
  `use_rag` tinyint DEFAULT 1,
  `llm_config_id` int DEFAULT NULL,
  `prompt_id` int DEFAULT NULL,
  `llm_question` text COMMENT '用户短问题，可为空',
  `llm_analysis` longtext,
  `rag_context` longtext,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_train` (`train_job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `llm_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `model_name` varchar(128) DEFAULT NULL,
  `api_key` varchar(255) DEFAULT NULL,
  `base_url` varchar(255) DEFAULT NULL,
  `temperature` decimal(6,3) DEFAULT 0.700,
  `max_tokens` int DEFAULT 2000,
  `system_prompt` text,
  `is_local_llm` tinyint DEFAULT 0,
  `is_default` tinyint DEFAULT 0,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `prompt_template` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `scene` varchar(64) DEFAULT NULL,
  `content` longtext,
  `placeholders` varchar(512) DEFAULT NULL,
  `is_default` tinyint DEFAULT 0,
  `qa_only` tinyint DEFAULT 0,
  `prompt_kind` varchar(32) DEFAULT 'system' COMMENT 'question=用户短问题 system=系统提示词',
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `insight_report` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(255) DEFAULT NULL,
  `train_job_id` int DEFAULT NULL,
  `predict_job_id` int DEFAULT NULL,
  `content` longtext,
  `rag_context` longtext,
  `llm_config_id` int DEFAULT NULL,
  `prompt_id` int DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `if_graph` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `scenario_code` varchar(64) DEFAULT 'generic',
  `description` varchar(512) DEFAULT NULL,
  `graph_json` longtext,
  `is_template` tinyint DEFAULT 0,
  `seed_key` varchar(64) DEFAULT NULL COMMENT '系统种子流程的稳定标识；为 NULL 表示用户自建',
  `schedule_kind` varchar(32) DEFAULT 'none',
  `schedule_enabled` tinyint DEFAULT 0,
  `schedule_last_at` datetime DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_scenario` (`scenario_code`),
  KEY `idx_seed_key` (`seed_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `if_graph_run` (
  `id` int NOT NULL AUTO_INCREMENT,
  `graph_id` int NOT NULL,
  `status` varchar(32) DEFAULT 'pending',
  `trigger_source` varchar(32) DEFAULT 'manual',
  `log_text` longtext,
  `result_json` longtext,
  `duration_sec` decimal(12,2) DEFAULT NULL,
  `error_message` text,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_graph` (`graph_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `if_node_run` (
  `id` int NOT NULL AUTO_INCREMENT,
  `run_id` int NOT NULL,
  `node_id` varchar(64) NOT NULL,
  `node_type` varchar(64) DEFAULT NULL,
  `status` varchar(32) DEFAULT 'pending',
  `message` varchar(512) DEFAULT NULL,
  `duration_sec` decimal(12,2) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_run` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `power_hourly` (
  `id` int NOT NULL AUTO_INCREMENT,
  `ts` datetime NOT NULL,
  `horizon` varchar(32) DEFAULT 'actual',
  `temp_c` decimal(8,2) DEFAULT NULL,
  `humidity` decimal(8,2) DEFAULT NULL,
  `precip_mm` decimal(8,2) DEFAULT NULL,
  `wind_10m` decimal(8,2) DEFAULT NULL,
  `wind_100m` decimal(8,2) DEFAULT NULL,
  `wind_gust` decimal(8,2) DEFAULT NULL,
  `radiation` decimal(10,2) DEFAULT NULL,
  `weather_code` int DEFAULT NULL,
  `load_mw` decimal(12,2) DEFAULT NULL,
  `wind_mw` decimal(12,2) DEFAULT NULL,
  `solar_mw` decimal(12,2) DEFAULT NULL,
  `residual_mw` decimal(12,2) DEFAULT NULL,
  `price_da` decimal(10,2) DEFAULT NULL,
  `price_rt` decimal(10,2) DEFAULT NULL,
  `congestion` decimal(8,4) DEFAULT NULL,
  `source_json` varchar(255) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ts_horizon` (`ts`, `horizon`),
  KEY `idx_ts` (`ts`),
  KEY `idx_horizon` (`horizon`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `power_alert` (
  `id` int NOT NULL AUTO_INCREMENT,
  `level` varchar(16) DEFAULT 'info',
  `code` varchar(64) DEFAULT NULL,
  `title` varchar(255) DEFAULT NULL,
  `message` text,
  `ts` datetime DEFAULT NULL,
  `status` varchar(32) DEFAULT 'open',
  `payload_json` longtext,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `power_report` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(255) DEFAULT NULL,
  `content` longtext,
  `rag_context` longtext,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `bi_board` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `description` varchar(512) DEFAULT NULL,
  `project_id` int DEFAULT NULL,
  `dataset_id` int DEFAULT NULL,
  `binding_id` int DEFAULT NULL,
  `grain` varchar(16) DEFAULT 'hour',
  `metrics_json` longtext,
  `horizons_json` longtext,
  `chart_type` varchar(32) DEFAULT 'line',
  `layout_json` longtext COMMENT 'FineBI 风格组件布局',
  `scenario_code` varchar(64) DEFAULT 'generic',
  `is_template` tinyint DEFAULT 0,
  `published` tinyint DEFAULT 1,
  `cover_color` varchar(32) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chat_session` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(128) DEFAULT NULL,
  `title_auto` tinyint DEFAULT 0 COMMENT '标题是否由 LLM 自动总结',
  `llm_config_id` int DEFAULT NULL,
  `prompt_id` int DEFAULT NULL,
  `use_rag` tinyint DEFAULT 1,
  `message_count` int DEFAULT 0,
  `last_message` varchar(512) DEFAULT NULL,
  `summary` text COMMENT '会话级滚动摘要（中长期记忆）',
  `summary_upto` int DEFAULT 0 COMMENT '摘要已覆盖到的消息 id',
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_update` (`update_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chat_message` (
  `id` int NOT NULL AUTO_INCREMENT,
  `session_id` int NOT NULL,
  `role` varchar(16) NOT NULL COMMENT 'user 或 assistant',
  `content` longtext,
  `snippets_json` longtext,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chat_memory` (
  `id` int NOT NULL AUTO_INCREMENT,
  `kind` varchar(16) DEFAULT 'fact' COMMENT 'fact=事实/偏好 session=会话摘要',
  `session_id` int DEFAULT NULL COMMENT '来源会话',
  `content` varchar(512) NOT NULL COMMENT '记忆正文',
  `keywords` varchar(512) DEFAULT NULL COMMENT '检索关键词',
  `weight` decimal(6,3) DEFAULT 1.000,
  `hits` int DEFAULT 0 COMMENT '被召回次数',
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_session` (`session_id`),
  KEY `idx_kind` (`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `realtime_sync_task` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `description` varchar(512) DEFAULT NULL,
  `mode` varchar(16) DEFAULT 'wizard' COMMENT 'wizard=向导模式 script=脚本模式',
  `source_id` int DEFAULT NULL COMMENT '关联 data_source.id',
  `database_name` varchar(128) DEFAULT NULL,
  `topic_prefix` varchar(64) DEFAULT 'cdc',
  `tables_json` longtext COMMENT '多表与主题映射 JSON',
  `channel_json` text COMMENT '通道控制参数 JSON',
  `generated_sql` longtext COMMENT '向导生成的 Flink SQL（脱敏）',
  `script_sql` longtext COMMENT '脚本模式用户编辑的 Flink SQL',
  `flink_job_id` varchar(128) DEFAULT NULL,
  `job_status` varchar(32) DEFAULT 'draft' COMMENT 'draft/running/stopped/failed',
  `last_checkpoint` varchar(512) DEFAULT NULL,
  `last_error` text,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_source` (`source_id`),
  KEY `idx_job_status` (`job_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `realtime_kafka_topic` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `partitions` int DEFAULT 1,
  `replication_factor` int DEFAULT 1,
  `retention_ms` bigint DEFAULT 604800000,
  `source_task_id` int DEFAULT NULL,
  `remark` varchar(512) DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  `username` varchar(64) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_topic_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
