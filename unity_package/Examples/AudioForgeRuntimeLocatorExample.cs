using System.Collections;
using UnityEngine;

/// <summary>
/// 示例：在业务层安全取得 AudioForgeRuntime，并在首次播放前确保运行时已完成初始化。
/// 建议把这段逻辑封装进你自己的 AudioService，而不是在每个业务脚本里重复写一遍。
/// </summary>
public sealed class AudioForgeRuntimeLocatorExample : MonoBehaviour
{
    [SerializeField] private string defaultEventId = "sfx_level_check_02";

    public void PlayDefaultEvent()
    {
        StartCoroutine(PlayEventWhenReady(defaultEventId));
    }

    public IEnumerator PlayEventWhenReady(string eventId)
    {
        AudioForgeRuntime runtime = AudioForgeRuntime.Instance;
        if (runtime == null)
        {
            runtime = FindObjectOfType<AudioForgeRuntime>();
        }

        if (runtime == null)
        {
            Debug.LogError("AudioForgeRuntime not found. Add AudioForgeBootstrap or AudioForgeRuntime to the scene first.");
            yield break;
        }

        if (!runtime.IsReady)
        {
            yield return runtime.Initialize();
        }

        if (!runtime.HasEvent(eventId))
        {
            Debug.LogWarning("AudioForge event not found: " + eventId);
            yield break;
        }

        runtime.Play(eventId);
    }
}