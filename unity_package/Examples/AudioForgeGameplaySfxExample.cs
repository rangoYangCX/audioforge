using System.Collections;
using UnityEngine;

/// <summary>
/// 示例：把常见 UI / 玩法动作映射成 AudioForge 事件和总线控制。
/// 这个脚本故意保留 Inspector 字段，方便程序和音频一起对照事件 Id 做联调。
/// </summary>
public sealed class AudioForgeGameplaySfxExample : MonoBehaviour
{
    [SerializeField] private string confirmEventId = "sfx_level_check_02";
    [SerializeField] private string cancelEventId = "sfx_level_check_03";
    [SerializeField] private string uiBusName = "UI";

    public void PlayConfirm()
    {
        StartCoroutine(PlayEventWhenReady(confirmEventId));
    }

    public void PlayCancel()
    {
        StartCoroutine(PlayEventWhenReady(cancelEventId));
    }

    public void SetUiBusMuted(bool isMuted)
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null || !runtime.IsReady)
        {
            return;
        }

        runtime.SetBusMuted(uiBusName, isMuted);
    }

    public void SetUiBusLinearVolume(float linearVolume)
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null || !runtime.IsReady)
        {
            return;
        }

        runtime.SetBusVolume(uiBusName, Mathf.Clamp01(linearVolume));
    }

    private IEnumerator PlayEventWhenReady(string eventId)
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null)
        {
            Debug.LogError("AudioForgeRuntime not found.");
            yield break;
        }

        if (!runtime.IsReady)
        {
            yield return runtime.Initialize();
        }

        runtime.Play(eventId);
    }

    private static AudioForgeRuntime ResolveRuntime()
    {
        if (AudioForgeRuntime.Instance != null)
        {
            return AudioForgeRuntime.Instance;
        }

        return FindObjectOfType<AudioForgeRuntime>();
    }
}