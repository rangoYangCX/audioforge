using System.Collections;
using UnityEngine;

[AddComponentMenu("AudioForge/AudioForge Bootstrap")]
[DisallowMultipleComponent]
/// <summary>
/// 空项目验证用的一键引导组件。
/// 会在场景中自动准备 Runtime 和 EventPlayer，方便 Unity 开发人员先验证契约和播放主链路。
/// </summary>
public sealed class AudioForgeBootstrap : MonoBehaviour
{
    private const string DefaultValidationEventId = "sfx_level_check_02";

    // 默认事件与仓库根目录 Export 样例保持一致，避免空项目验证仍指向历史事件名。
    public string EventId = DefaultValidationEventId;
    public bool AutoPlayOnStart = true;
    public KeyCode TriggerKey = KeyCode.Space;
    public float LocalEventVolumeDbOffset;

    private AudioForgeRuntime _runtime;
    private AudioForgeEventPlayer _eventPlayer;

    private IEnumerator Start()
    {
        // 先复用已有 Runtime；如果场景里没有，就临时创建一个参考 Runtime。
        _runtime = AudioForgeRuntime.Instance;
        if (_runtime == null)
        {
            _runtime = FindObjectOfType<AudioForgeRuntime>();
        }

        if (_runtime == null)
        {
            _runtime = gameObject.AddComponent<AudioForgeRuntime>();
        }

        // EventPlayer 负责把“输入/触发”转成对 Runtime 的一次播放调用。
        _eventPlayer = GetComponent<AudioForgeEventPlayer>();
        if (_eventPlayer == null)
        {
            _eventPlayer = gameObject.AddComponent<AudioForgeEventPlayer>();
        }

        _eventPlayer.Runtime = _runtime;
        _eventPlayer.EventId = EventId;
        _eventPlayer.OverrideAudioSource = GetComponent<AudioSource>();
        _eventPlayer.UseAttachedAudioSource = _eventPlayer.OverrideAudioSource != null;
        _eventPlayer.TriggerKey = KeyCode.None;
        _eventPlayer.LocalEventVolumeDbOffset = LocalEventVolumeDbOffset;

        yield return _runtime.Initialize();
        if (AutoPlayOnStart)
        {
            _eventPlayer.Play();
        }
    }

    private void Update()
    {
        if (_runtime == null || !_runtime.IsReady)
        {
            return;
        }

        if (_eventPlayer != null)
        {
            _eventPlayer.EventId = EventId;
            _eventPlayer.LocalEventVolumeDbOffset = LocalEventVolumeDbOffset;
        }

        if (Input.GetKeyDown(TriggerKey))
        {
            _eventPlayer.Play();
        }
    }
}