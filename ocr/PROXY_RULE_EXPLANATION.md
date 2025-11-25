# 代理规则工作原理说明

## 为什么一个规则就能让所有端点工作？

### 问题
为什么在mihomo配置中只设置了：
```yaml
rules:
  - DOMAIN,localhost,DIRECT
```

就能让以下两个不同的端点都正常工作？
- `http://localhost:8765/health` ✅
- `http://localhost:8765/ocr` ✅

### 答案：代理规则是基于域名/IP匹配的，不是基于路径

## HTTP请求的组成部分

一个完整的HTTP请求URL包含以下部分：

```
http://localhost:8765/health
│    │          │    │
│    │          │    └─ 路径 (Path)
│    │          └─────── 端口 (Port)
│    └────────────────── 域名/主机 (Domain/Host)
└─────────────────────── 协议 (Protocol)
```

## 代理规则匹配机制

### 1. 规则匹配顺序

mihomo/clash代理在匹配规则时，**只关注域名/IP部分**，不关心路径：

```
请求: http://localhost:8765/health
      │
      ▼
代理检查域名: localhost
      │
      ▼
匹配规则: DOMAIN,localhost,DIRECT
      │
      ▼
应用规则: 直连（不走代理）
      │
      ▼
请求直接发送到 localhost:8765
      │
      ▼
服务器处理: /health 路径
```

### 2. 为什么所有路径都生效？

因为规则匹配发生在**域名解析阶段**，而不是路径处理阶段：

```
┌─────────────────────────────────────────┐
│  1. 请求到达代理                        │
│     http://localhost:8765/health        │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  2. 代理解析URL                         │
│     - 域名: localhost                   │
│     - 端口: 8765                        │
│     - 路径: /health  ← 此时还未处理     │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  3. 匹配规则（只看域名）                │
│     DOMAIN,localhost,DIRECT ✅          │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  4. 应用规则：直连                      │
│     整个请求（包括所有路径）都直连       │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  5. 请求发送到目标服务器                │
│     localhost:8765/health               │
│     localhost:8765/ocr                   │
│     localhost:8765/任何路径              │
└─────────────────────────────────────────┘
```

## 实际示例

### 示例1: Health检查
```python
requests.get("http://localhost:8765/health")
```

**代理处理流程：**
1. 解析URL：域名=`localhost`
2. 匹配规则：`DOMAIN,localhost,DIRECT` ✅
3. 应用规则：直连
4. 发送请求：直接到 `localhost:8765/health`

### 示例2: OCR请求
```python
requests.post("http://localhost:8765/ocr", json={...})
```

**代理处理流程：**
1. 解析URL：域名=`localhost`
2. 匹配规则：`DOMAIN,localhost,DIRECT` ✅
3. 应用规则：直连
4. 发送请求：直接到 `localhost:8765/ocr`

### 示例3: 任何其他路径
```python
requests.get("http://localhost:8765/api/v1/test")
requests.get("http://localhost:8765/anything")
```

**结果：** 都会直连，因为域名都是 `localhost`

## 规则类型说明

### DOMAIN规则
```yaml
- DOMAIN,localhost,DIRECT
```
- **匹配方式：** 精确匹配域名
- **作用范围：** 该域名的所有端口、所有路径
- **示例匹配：**
  - ✅ `http://localhost/health`
  - ✅ `http://localhost:8765/ocr`
  - ✅ `http://localhost:8080/api`
  - ❌ `http://localhost.example.com` (子域名不匹配)

### IP-CIDR规则（如果添加）
```yaml
- IP-CIDR,127.0.0.0/8,DIRECT
```
- **匹配方式：** 匹配IP地址范围
- **作用范围：** 该IP范围的所有端口、所有路径
- **示例匹配：**
  - ✅ `http://127.0.0.1:8765/health`
  - ✅ `http://127.0.0.1:8080/ocr`
  - ✅ `http://127.1.2.3:9999/anything`

## 为什么不需要为每个路径配置规则？

### ❌ 错误理解
```yaml
rules:
  - DOMAIN,localhost/health,DIRECT    # 错误：这不是有效规则
  - DOMAIN,localhost/ocr,DIRECT       # 错误：路径不是规则的一部分
```

### ✅ 正确理解
```yaml
rules:
  - DOMAIN,localhost,DIRECT  # 一个规则覆盖所有路径
```

**原因：**
1. 代理规则系统设计为基于**网络层**（域名/IP）匹配
2. 路径（Path）是**应用层**的概念，由目标服务器处理
3. 代理只负责路由，不关心具体的API端点

## 类比理解

可以把代理规则想象成**邮局分拣系统**：

```
信件地址: localhost:8765/health
          │        │    │
          │        │    └─ 房间号（路径）- 邮局不关心
          │        └────── 街道号（端口）- 邮局不关心
          └─────────────── 城市名（域名）- 邮局根据这个分拣
```

邮局（代理）只根据**城市名（域名）**决定：
- 如果城市是"localhost" → 本地投递（DIRECT）
- 如果城市是"google.com" → 通过代理投递

至于具体是哪个房间（路径），由**本地邮递员（目标服务器）**处理。

## 总结

1. **一个规则覆盖所有路径**：`DOMAIN,localhost,DIRECT` 匹配所有 `localhost` 的请求
2. **规则基于域名/IP**：不关心端口和路径
3. **路径由服务器处理**：代理只负责路由，路径由目标服务器解析
4. **这是标准设计**：所有HTTP代理都是这样工作的

因此，只需要一个 `DOMAIN,localhost,DIRECT` 规则，就能让所有 `localhost` 的请求（无论什么路径）都直连！

