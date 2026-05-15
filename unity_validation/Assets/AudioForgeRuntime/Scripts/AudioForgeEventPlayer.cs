using System.Collections;
using UnityEngine;

[AddComponentMenu("AudioForge/AudioForge Event Player")]
[DisallowMultipleComponent]
/// <summary>
/// 事件触发器参考组件。
/// 负责把 Start / Enable / 按键 等输入时机，转换成对 AudioForgeRuntime 的播放调用。
/// </summary>
public sealed class AudioForgeEventPlayer : MonoBehaviour
{
    private const string DefaultValidationEventId = "sfx_level_check_02";

    public AudioForgeRuntime Runtime;
    // 默认事件与仓库当前 Export 样例对齐，便于直接复制验证包后立即触发声音。
    public string EventId = DefaultValidationEventId;
    public bool PlayOnStart;
    public bool TriggerOnEnable;
    public bool UseAttachedAudioSource;
    public bool UseEmitterContext = true;
    public KeyCode TriggerKey = KeyCode.None;
    public float LocalEventVolumeDbOffset;

    [HideInInspector] public AudioSource OverrideAudioSource;
    private AudioForgeEmitterHandle _emitterHandle;

    private IEnumerator Start()
    {
        if (PlayOnStart)
        {
            yield return PlayRoutine();
        }
    }

    private void OnEnable()
    {
        if (TriggerOnEnable)
        {
            StartCoroutine(PlayRoutine());
        }
    }

    private void Update()
    {
        if (TriggerKey != KeyCode.None && Input.GetKeyDown(TriggerKey))
        {
            Play();
        }
    }

    public void Play()
    {
        StartCoroutine(PlayRoutine());
    }

    public void SetSwitch(string groupName, string switchName)
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null)
        {
            return;
        }
        EnsureEmitterHandle(runtime);
        runtime.SetSwitch(_emitterHandle, groupName, switchName);
    }

    public void SetEmitterGameParameter(string name, float value)
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null)
        {
            return;
        }
        EnsureEmitterHandle(runtime);
        runtime.SetEmitterGameParameter(_emitterHandle, name, value);
    }

    public void SetGameParameter(string name, float value)
    {
        SetEmitterGameParameter(name, value);
    }

    private void OnDestroy()
    {
        if (Runtime != null && _emitterHandle != null)
        {
            Runtime.UnregisterEmitter(_emitterHandle);
        }
    }

    private IEnumerator PlayRoutine()
    {
        AudioForgeRuntime runtime = ResolveRuntime();
        if (runtime == null)
        {
            yield break;
        }

        // 参考实现允许事件播放器在 Runtime 尚未初始化时主动触发初始化。
        if (!runtime.IsReady)
        {
            yield return runtime.Initialize();
        }

        AudioSource source = null;
        if (UseAttachedAudioSource)
        {
            source = OverrideAudioSource != null ? OverrideAudioSource : GetComponent<AudioSource>();
        }

        if (UseEmitterContext)
        {
            EnsureEmitterHandle(runtime);
            yield return runtime.PlayEvent(EventId, _emitterHandle, source, LocalEventVolumeDbOffset);
            yield break;
        }

        yield return runtime.PlayEvent(EventId, source, LocalEventVolumeDbOffset);
    }

    private AudioForgeRuntime ResolveRuntime()
    {
        if (Runtime != null)
        {
            return Runtime;
        }

        if (AudioForgeRuntime.Instance != null)
        {
            Runtime = AudioForgeRuntime.Instance;
            return Runtime;
        }

        Runtime = FindObjectOfType<AudioForgeRuntime>();
        return Runtime;
    }

    private void EnsureEmitterHandle(AudioForgeRuntime runtime)
    {
        if (_emitterHandle != null)
        {
            return;
        }
        _emitterHandle = runtime.RegisterEmitter(gameObject);
    }
}