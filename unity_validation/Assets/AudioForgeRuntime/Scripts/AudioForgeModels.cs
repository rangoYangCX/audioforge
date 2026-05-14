using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Audio;

/// <summary>
/// 单个导出音频片段配置。
/// 这部分数据完全来自 AudioData.json，Unity 侧不应自行发明额外规则去覆盖它。
/// </summary>
[Serializable]
public sealed class AudioForgeClipConfig
{
    public string ClipId;
    public string AssetKey;
    public int Weight;
    public int TrimStartMs;
    public int TrimEndMs;
    public int FadeInMs;
    public int FadeOutMs;
    public int LoopStartMs;
    public int LoopEndMs;
}

/// <summary>
/// 单个总线的导出配置。
/// 运行时初始化时应优先读取这里的音量与静音状态。
/// </summary>
[Serializable]
public sealed class AudioForgeBusConfig
{
    public string Name;
    public string ParentBus;
    public float VolumeDb;
    public bool IsMuted;
    public List<AudioForgeRtpcBindingConfig> RtpcBindings = new List<AudioForgeRtpcBindingConfig>();
    public List<AudioForgeStateOverrideConfig> StateOverrides = new List<AudioForgeStateOverrideConfig>();
}

[Serializable]
public sealed class AudioForgeCurvePointConfig
{
    public float InputValue;
    public float OutputValue;
    public string Interpolation;
}

[Serializable]
public sealed class AudioForgeRtpcBindingConfig
{
    public string ParameterName;
    public string Target;
    public string Scope;
    public List<AudioForgeCurvePointConfig> CurvePoints = new List<AudioForgeCurvePointConfig>();
}

[Serializable]
public sealed class AudioForgeStateOverrideConfig
{
    public string GroupName;
    public string StateName;
    public float VolumeDb;
    public int PitchCents;
    public bool IsMuted;
}

[Serializable]
public sealed class AudioForgeSwitchVariantConfig
{
    public string GroupName;
    public string SwitchName;
    public List<string> ClipIds = new List<string>();
}

[Serializable]
public sealed class AudioForgeGameParameterConfig
{
    public string Name;
    public float DefaultValue;
    public float MinValue;
    public float MaxValue;
    public string Description;
}

[Serializable]
public sealed class AudioForgeStateGroupConfig
{
    public string Name;
    public string DefaultState;
    public List<string> States = new List<string>();
    public List<AudioForgeGameSyncEffectConfig> StateEffects = new List<AudioForgeGameSyncEffectConfig>();
}

[Serializable]
public sealed class AudioForgeGameSyncEffectConfig
{
    public string ValueName;
    public float VolumeDb;
    public int PitchCents;
    public bool IsMuted;
    public string Notes;
}

[Serializable]
public sealed class AudioForgeSwitchThresholdConfig
{
    public string SwitchName;
    public float MinValue;
    public float MaxValue;
}

[Serializable]
public sealed class AudioForgeSwitchGroupConfig
{
    public string Name;
    public string DefaultSwitch;
    public List<string> Switches = new List<string>();
    public bool UseGameParameter;
    public string MappedGameParameter;
    public List<AudioForgeSwitchThresholdConfig> Thresholds = new List<AudioForgeSwitchThresholdConfig>();
    public List<AudioForgeGameSyncEffectConfig> SwitchEffects = new List<AudioForgeGameSyncEffectConfig>();
}

/// <summary>
/// 项目级 Audio Object 配置。
/// 事件只通过 AudioId 引用这里的对象。
/// </summary>
[Serializable]
public sealed class AudioForgeAudioObjectConfig
{
    public string AudioId;
    public string DisplayName;
    public string Bus;
    public string PlayMode;
    public bool AvoidImmediateRepeat;
    public float VolumeDb;
    public float VolumeRandMinDb;
    public float VolumeRandMaxDb;
    public int PitchCents;
    public int PitchRandMinCents;
    public int PitchRandMaxCents;
    public string LoadPolicy;
    public int ComboPitchStepCents;
    public float ComboResetSeconds;
    public int ComboMaxStep;
    public List<string> DefaultClipIds = new List<string>();
    public List<AudioForgeClipConfig> Clips = new List<AudioForgeClipConfig>();
    public List<AudioForgeRtpcBindingConfig> RtpcBindings = new List<AudioForgeRtpcBindingConfig>();
    public List<AudioForgeStateOverrideConfig> StateOverrides = new List<AudioForgeStateOverrideConfig>();
    public List<AudioForgeSwitchVariantConfig> SwitchVariants = new List<AudioForgeSwitchVariantConfig>();
}

/// <summary>
/// 单个事件的运行时配置。
/// 参考运行时只消费导出数据，不读取 .afproj。
/// </summary>
[Serializable]
public sealed class AudioForgeEventConfig
{
    public string EventId;
    public int MaxInstances;
    public float CooldownSeconds;
    public string StealPolicy;
    public string AudioId;
    public AudioForgeAudioObjectConfig Audio = new AudioForgeAudioObjectConfig();

    public string Bus
    {
        get { return Audio != null ? Audio.Bus : string.Empty; }
        set
        {
            EnsureAudio();
            Audio.Bus = value;
        }
    }

    public string PlayMode
    {
        get { return Audio != null ? Audio.PlayMode : string.Empty; }
        set
        {
            EnsureAudio();
            Audio.PlayMode = value;
        }
    }

    public bool AvoidImmediateRepeat
    {
        get { return Audio != null && Audio.AvoidImmediateRepeat; }
        set
        {
            EnsureAudio();
            Audio.AvoidImmediateRepeat = value;
        }
    }

    public float VolumeDb
    {
        get { return Audio != null ? Audio.VolumeDb : 0f; }
        set
        {
            EnsureAudio();
            Audio.VolumeDb = value;
        }
    }

    public float VolumeRandMinDb
    {
        get { return Audio != null ? Audio.VolumeRandMinDb : 0f; }
        set
        {
            EnsureAudio();
            Audio.VolumeRandMinDb = value;
        }
    }

    public float VolumeRandMaxDb
    {
        get { return Audio != null ? Audio.VolumeRandMaxDb : 0f; }
        set
        {
            EnsureAudio();
            Audio.VolumeRandMaxDb = value;
        }
    }

    public int PitchCents
    {
        get { return Audio != null ? Audio.PitchCents : 0; }
        set
        {
            EnsureAudio();
            Audio.PitchCents = value;
        }
    }

    public int PitchRandMinCents
    {
        get { return Audio != null ? Audio.PitchRandMinCents : 0; }
        set
        {
            EnsureAudio();
            Audio.PitchRandMinCents = value;
        }
    }

    public int PitchRandMaxCents
    {
        get { return Audio != null ? Audio.PitchRandMaxCents : 0; }
        set
        {
            EnsureAudio();
            Audio.PitchRandMaxCents = value;
        }
    }

    public string LoadPolicy
    {
        get { return Audio != null ? Audio.LoadPolicy : string.Empty; }
        set
        {
            EnsureAudio();
            Audio.LoadPolicy = value;
        }
    }

    public int ComboPitchStepCents
    {
        get { return Audio != null ? Audio.ComboPitchStepCents : 0; }
        set
        {
            EnsureAudio();
            Audio.ComboPitchStepCents = value;
        }
    }

    public float ComboResetSeconds
    {
        get { return Audio != null ? Audio.ComboResetSeconds : 0f; }
        set
        {
            EnsureAudio();
            Audio.ComboResetSeconds = value;
        }
    }

    public int ComboMaxStep
    {
        get { return Audio != null ? Audio.ComboMaxStep : 0; }
        set
        {
            EnsureAudio();
            Audio.ComboMaxStep = value;
        }
    }

    public List<string> DefaultClipIds
    {
        get
        {
            EnsureAudio();
            return Audio.DefaultClipIds;
        }
        set
        {
            EnsureAudio();
            Audio.DefaultClipIds = value ?? new List<string>();
        }
    }

    public List<AudioForgeClipConfig> Clips
    {
        get
        {
            EnsureAudio();
            return Audio.Clips;
        }
        set
        {
            EnsureAudio();
            Audio.Clips = value ?? new List<AudioForgeClipConfig>();
        }
    }

    public List<AudioForgeRtpcBindingConfig> RtpcBindings
    {
        get
        {
            EnsureAudio();
            return Audio.RtpcBindings;
        }
        set
        {
            EnsureAudio();
            Audio.RtpcBindings = value ?? new List<AudioForgeRtpcBindingConfig>();
        }
    }

    public List<AudioForgeStateOverrideConfig> StateOverrides
    {
        get
        {
            EnsureAudio();
            return Audio.StateOverrides;
        }
        set
        {
            EnsureAudio();
            Audio.StateOverrides = value ?? new List<AudioForgeStateOverrideConfig>();
        }
    }

    public List<AudioForgeSwitchVariantConfig> SwitchVariants
    {
        get
        {
            EnsureAudio();
            return Audio.SwitchVariants;
        }
        set
        {
            EnsureAudio();
            Audio.SwitchVariants = value ?? new List<AudioForgeSwitchVariantConfig>();
        }
    }

    private void EnsureAudio()
    {
        if (Audio == null)
        {
            Audio = new AudioForgeAudioObjectConfig();
        }
    }
}

/// <summary>
/// AudioData.json 的根数据结构。
/// </summary>
[Serializable]
public sealed class AudioForgeDatabase
{
    public int SchemaVersion;
    public string ProjectName;
    public string RuntimeAudioFormat;
    public List<string> Buses = new List<string>();
    public List<AudioForgeBusConfig> BusConfigs = new List<AudioForgeBusConfig>();
    public List<AudioForgeGameParameterConfig> GameParameters = new List<AudioForgeGameParameterConfig>();
    public List<AudioForgeStateGroupConfig> StateGroups = new List<AudioForgeStateGroupConfig>();
    public List<AudioForgeSwitchGroupConfig> SwitchGroups = new List<AudioForgeSwitchGroupConfig>();
    public List<AudioForgeAudioObjectConfig> AudioObjects = new List<AudioForgeAudioObjectConfig>();
    public List<AudioForgeEventConfig> Events = new List<AudioForgeEventConfig>();
}

public sealed class AudioForgeEmitterHandle
{
    public string EmitterId;
    public GameObject BoundGameObject;
}

public sealed class AudioForgeEmitterContext
{
    public string EmitterId;
    public GameObject BoundGameObject;
    public readonly Dictionary<string, float> LocalGameParameters = new Dictionary<string, float>();
    public readonly Dictionary<string, string> LocalSwitches = new Dictionary<string, string>();
}

/// <summary>
/// 单个事件在运行时维护的状态。
/// 包括 Sequence 游标、Combo 步数、上次触发时间和活动声部。
/// </summary>
public sealed class AudioForgeRuntimeState
{
    public string LastClipId;
    public int SequenceIndex;
    public int ComboStep;
    public float LastTriggerTime = -999f;
    public readonly List<AudioForgeActiveVoice> ActiveVoices = new List<AudioForgeActiveVoice>();
}

/// <summary>
/// 单条活动声部的运行时信息。
/// </summary>
public sealed class AudioForgeActiveVoice
{
    public AudioSource Source;
    public string EventId;
    public string EmitterId;
    public string BusName;
    public bool ManagedByPool;
    public float StartedAtTime;
    public float BaseVolume;
    public int BasePitchCents;
}

/// <summary>
/// 单个总线在运行时维护的状态。
/// </summary>
public sealed class AudioForgeBusState
{
    public string Name;
    public string ParentBusName;
    public GameObject RootObject;
    public float Volume = 1f;
    public float UnityVolume = 1f;
    public bool IsMuted;
    public AudioMixerGroup OutputMixerGroup;
    public readonly List<AudioSource> ActiveSources = new List<AudioSource>();
    public readonly Queue<AudioSource> IdleSources = new Queue<AudioSource>();
}

[Serializable]
public sealed class AudioForgeUnityBusMixerBinding
{
    public string BusName;
    public AudioMixerGroup OutputMixerGroup;
    [Range(0f, 1f)] public float Volume = 1f;
}

[Serializable]
public sealed class AudioForgeUnityEventVolumeBinding
{
    public string EventId;
    public float VolumeDbOffset;
}

/// <summary>
/// 最近一次事件触发的调试记录。
/// 用于在参考调试面板中直观看到：命中片段、总音高、是否走保时长、缓存是否命中、触发是否被拒绝。
/// </summary>
public sealed class AudioForgeDebugEventRecord
{
    public string EventId;
    public string ClipId;
    public string AssetKey;
    public string BusName;
    public string Result;
    public string Message;
    public int TrimStartMs;
    public int TrimEndMs;
    public int FadeInMs;
    public int FadeOutMs;
    public int LoopStartMs;
    public int LoopEndMs;
    public float VolumeDb;
    public int PitchCents;
    public int ComboStep;
    public bool UsedTimePreservingPitch;
    public bool CacheHit;
    public float Timestamp;
}

/// <summary>
/// 最近一次总线状态变化的调试记录。
/// </summary>
public sealed class AudioForgeDebugBusRecord
{
    public string BusName;
    public string Action;
    public float Volume;
    public bool IsMuted;
    public float Timestamp;
}