using UnityEngine;

/// <summary>
/// 示例：在 Runtime.Initialize() 之前，给 AudioForgeRuntime 注入自定义资源提供器。
/// 把这个脚本挂在比第一次播放更早执行的对象上，就能把默认 StreamingAssets 加载改成项目自己的方案。
/// </summary>
public sealed class AudioForgeRuntimeInstallerExample : MonoBehaviour
{
    [SerializeField] private AudioForgeRuntime runtime;
    [SerializeField] private string resourcesRoot = "AudioForge";

    private void Awake()
    {
        if (runtime == null)
        {
            runtime = AudioForgeRuntime.Instance != null
                ? AudioForgeRuntime.Instance
                : FindObjectOfType<AudioForgeRuntime>();
        }

        if (runtime == null)
        {
            Debug.LogWarning("AudioForgeRuntime not found. Add AudioForgeRuntime or AudioForgeBootstrap before installing a custom provider.");
            return;
        }

        // 关键点：必须在第一次 Initialize() 之前完成注入，后续所有 Play 流程才会统一走自定义 provider。
        runtime.SetResourceProvider(new AudioForgeResourcesProviderExample(resourcesRoot));
    }
}