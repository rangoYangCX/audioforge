using System;
using System.Collections;
using UnityEngine;

/// <summary>
/// 运行时资源提供器抽象。
/// 生产项目可以把这里替换成 Addressables、AssetBundle 或自定义 CDN 拉取实现；
/// 参考项目默认使用 StreamingAssets 版本。
/// </summary>
public interface IAudioForgeResourceProvider
{
    IEnumerator LoadClip(string assetKey, string runtimeAudioFormat, Action<AudioClip> onLoaded);
}