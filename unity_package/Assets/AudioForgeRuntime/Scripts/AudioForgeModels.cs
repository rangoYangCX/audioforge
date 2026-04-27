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
}

/// <summary>
/// 单个事件的运行时配置。
/// 参考运行时只消费导出数据，不读取 .afproj。
/// </summary>
[Serializable]
public sealed class AudioForgeEventConfig
{
    public string EventId;
    public string Bus;
    public string PlayMode;
    public bool AvoidImmediateRepeat;
    public float VolumeDb;
    public float VolumeRandMinDb;
    public float VolumeRandMaxDb;
    public int PitchCents;
    public int PitchRandMinCents;
    public int PitchRandMaxCents;
    public int MaxInstances;
    public float CooldownSeconds;
    public string StealPolicy;
    public string LoadPolicy;
    public int ComboPitchStepCents;
    public float ComboResetSeconds;
    public int ComboMaxStep;
    public List<AudioForgeClipConfig> Clips = new List<AudioForgeClipConfig>();
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
    public List<AudioForgeEventConfig> Events = new List<AudioForgeEventConfig>();
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
    public string BusName;
    public bool ManagedByPool;
    public float StartedAtTime;
    public float BaseVolume;
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