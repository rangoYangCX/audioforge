# StreamingAssets Layout

当前文档同步日期：2026-05-11

把工具导出的运行时数据放到这里。

推荐结构：

```text
Assets/StreamingAssets/AudioForge/
  AudioData.json
  AudioManifest.json
  Assets/
    ...导出的音频资源...
```

说明：

- `AudioData.json` 是运行时主数据入口。
- `AudioManifest.json` 用于资源映射和导出结果审查。
- `Assets/` 下是导出的运行时音频资源目录；实际扩展名以 `AudioData.json` 里的 `RuntimeAudioFormat` 为准。
- 2026-05-11 的桌面工具维护更新不改变这里的目录结构，只刷新交付文档、验证基线与未来重新导出时的工作台行为说明。
