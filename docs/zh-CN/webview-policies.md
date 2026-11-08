# WebView 策略回调

运行期 `WebviewWindowBuilder.build/from_config/build_async` 支持三个同步策略回调。
回调可能在 GUI 或协议工作线程执行，不得等待 GUI、同步建窗或执行阻塞网络操作。
异常、awaitable 和错误返回触发有序退出；退出后由 `App.run_return()` 归还原始 Python 异常。
每个回调绑定创建时的窗口代次，窗口销毁或应用退出释放回调；同名窗口不会恢复旧回调。

## 新窗口

```python
from pytaurix import NewWindowFeatures, NewWindowResponse

def on_new_window(url: str, features: NewWindowFeatures) -> NewWindowResponse:
    return NewWindowResponse.Deny
```

`features.size/position` 为逻辑像素二元组或 None，可以在回调后保留快照。
`Allow` 交给平台默认弹窗实现，仍受浏览器用户激活等策略限制；不自动获得本框架窗口注册或 IPC 权限。
`Deny` 拒绝请求。不能用 bool/字符串替代枚举。
上游 `Create` 要求共享 WebView 环境/配置，当前未绑定，不提供不安全的同步建窗回退。

## 浏览器权限

```python
from pytaurix import PermissionKind, PermissionResponse, Webview

def on_permission(view: Webview, kind: PermissionKind) -> PermissionResponse:
    return PermissionResponse.Deny
```

`Allow/Deny/Default` 分别交给上游授权、拒绝或平台默认路径；Linux 的 Default 是拒绝。
各平台仅支持 `PermissionKind` 的部分种类。浏览器已有持久化决定时可能不触发回调。
`view` 是所属窗口代次的受限 WebView 视图；上游未提供本次请求的来源 URL，
因此不要只凭初始页面 URL 授予可能发生导航的远程页面。宿主 ACL 与浏览器权限是独立边界。

## 应用资源请求

```python
from pytaurix import WebResourceRequest, WebResourceResponse

def on_resource(request: WebResourceRequest, original: WebResourceResponse) -> WebResourceResponse | None:
    if request.url.endswith("/health.html"):
        return WebResourceResponse(200, (("content-type", b"text/plain"),), b"ok")
    return None
```

这是 Tauri 应用资源协议响应钩子，不能拦截任意 HTTP(S) 网络流量。
请求包含 `url/method/headers/body`，响应包含 `status/headers/body`。
`headers` 是名称与原始字节值的不可变元组，保留重复头；`body` 是独立 bytes 副本。
返回 None 保持原响应；返回完整 `WebResourceResponse` 替换状态、所有头部及正文。
宿主替换 HTML 时需要自行保留所需 CSP 和内容类型，替换正文后不得沿用不匹配的 Content-Length。

状态码限 100–599，正文要求 bytes，头部要求合法 HTTP 名称与字节值。
框架先完整校验、构建新响应，再一次替换；失败时清空原响应并返回空 500，不向页面暴露异常正文。
复制请求和原响应会占用与载荷相关的额外内存，钩子只在显式注册时安装。

## 运行与限制

示例：`examples/webview_policy/main.py`；专项验收：`scripts/webview_policy_smoke.py`。
窗口配置文件创建的窗口没有这些运行期回调；需要使用 Python 构建器注册。
此批 API 是 0.1.0a1 开发工作区的新增契约，尚未公开发行。
平台实际验收和缺口见 [第十三阶段方案](system-webview-stage-plan.md)。

## WebView 数据目录

运行期 Builder 的 `data_directory=Path(...)` 要求绝对路径，并直接调用上游 Builder 数据目录接口。
目录由宿主拥有并负责保存/删除，框架不自动清理。示例使用自有 TemporaryDirectory 并由父进程在 WebView 子进程退出后清理；原生浏览器可能异步释放文件，清理重试有界且失败可见。
这与 `WindowConfig.dataDirectory` 的相对本地数据目录规则不同，不能把绝对路径放入配置后假定生效。

## 验收边界

Windows 定向验收覆盖资源响应保留/替换、新窗口拒绝、Geolocation 权限拒绝及九种失败恢复。
`NewWindowResponse.Allow` 的平台默认效果、`PermissionResponse.Allow/Default` 的实际授权和其余权限种类没有计为通过。
原生平台默认弹窗可能在宿主注册之外创建窗口，测试不会控制未知浏览器 PID。
Windows `is_focused()` 查询包含前台 WebView 子控件，原生 Focused 事件保留上游父窗口语义。
