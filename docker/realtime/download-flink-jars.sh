#!/usr/bin/env bash
# 下载 Flink 1.18 所需的 MySQL CDC / Kafka / MySQL JDBC 连接器 JAR，并初始化目录
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
mkdir -p "$LIB_DIR" "$SCRIPT_DIR/state/checkpoints" "$SCRIPT_DIR/state/savepoints" "$SCRIPT_DIR/sql"
chmod -R 777 "$SCRIPT_DIR/state"

MAVEN_BASE="${MAVEN_BASE:-https://repo1.maven.org/maven2}"

download_jar() {
  local name="$1"
  local url="$2"
  if [ -f "$LIB_DIR/$name" ]; then
    echo "  已存在: $name"
    return
  fi
  echo "  下载: $name"
  curl -fL --retry 3 -o "$LIB_DIR/$name" "$url"
}

download_jar "flink-sql-connector-mysql-cdc-3.1.1.jar" \
  "$MAVEN_BASE/org/apache/flink/flink-sql-connector-mysql-cdc/3.1.1/flink-sql-connector-mysql-cdc-3.1.1.jar"

download_jar "flink-sql-connector-kafka-3.2.0-1.18.jar" \
  "$MAVEN_BASE/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.18/flink-sql-connector-kafka-3.2.0-1.18.jar"

download_jar "mysql-connector-j-8.0.33.jar" \
  "$MAVEN_BASE/com/mysql/mysql-connector-j/8.0.33/mysql-connector-j-8.0.33.jar"

echo "连接器与状态目录准备完成：$LIB_DIR"
