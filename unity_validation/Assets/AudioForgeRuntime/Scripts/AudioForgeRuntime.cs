using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Audio;

[AddComponentMenu("AudioForge/AudioForge Runtime")]
[DisallowMultipleComponent]
/// <summary>
/// Unity 侧参考运行时入口。
/// 负责加载导出数据、管理事件/总线状态、分配 AudioSource，并串起默认的保时长变调参考链路。
/// </summary>
public sealed class AudioForgeRuntime : MonoBehaviour
{
    private const int MaxDebugEventRecords = 48;
    private const int MaxDebugBusRecords = 32;

    [SerializeField] private bool persistAcrossScenes = true;
    [SerializeField] private int prewarmedSourcesPerBus = 2;
    [SerializeField] private int maxSourcesPerBus = 16;
    [SerializeField] private string masterBusName = "Master";
    [SerializeField] private bool useReferenceTimePreservingPitch = true;
    [Header("Unity Audio Mixer")]
    [SerializeField] private bool integrateWithUnityAudioMixer = false;
    [SerializeField] private AudioMixerGroup defaultOutputMixerGroup;
    [SerializeField] [Range(0f, 1f)] private float unityMasterVolume = 1f;
    [SerializeField] private List<AudioForgeUnityBusMixerBinding> unityBusMixerBindings = new List<AudioForgeUnityBusMixerBinding>();
    [SerializeField] private List<AudioForgeUnityEventVolumeBinding> unityEventVolumeBindings = new List<AudioForgeUnityEventVolumeBinding>();

    private readonly Dictionary<string, AudioForgeEventConfig> _events = new Dictionary<string, AudioForgeEventConfig>();
    private readonly Dictionary<string, AudioClip> _clips = new Dictionary<string, AudioClip>();
    private readonly Dictionary<string, AudioClip> _processedClips = new Dictionary<string, AudioClip>();
    private readonly Dictionary<string, AudioForgeRuntimeState> _states = new Dictionary<string, AudioForgeRuntimeState>();
    private readonly Dictionary<string, AudioForgeBusState> _buses = new Dictionary<string, AudioForgeBusState>();
    private readonly Dictionary<string, AudioForgeGameParameterConfig> _gameParameterConfigs = new Dictionary<string, AudioForgeGameParameterConfig>();
    private readonly Dictionary<string, AudioForgeStateGroupConfig> _stateGroupConfigs = new Dictionary<string, AudioForgeStateGroupConfig>();
    private readonly Dictionary<string, AudioForgeSwitchGroupConfig> _switchGroupConfigs = new Dictionary<string, AudioForgeSwitchGroupConfig>();
    private readonly Dictionary<string, float> _globalGameParameters = new Dictionary<string, float>();
    private readonly Dictionary<string, string> _globalStates = new Dictionary<string, string>();
    private readonly Dictionary<string, AudioForgeEmitterContext> _emitters = new Dictionary<string, AudioForgeEmitterContext>();
    private readonly List<AudioForgeDebugEventRecord> _debugEventRecords = new List<AudioForgeDebugEventRecord>();
    private readonly List<AudioForgeDebugBusRecord> _debugBusRecords = new List<AudioForgeDebugBusRecord>();
    private readonly System.Random _random = new System.Random();
    private string _runtimeAudioFormat = "ogg";
    private IAudioForgeResourceProvider _resourceProvider;
    private IAudioForgeResourceProvider _resourceProviderOverride;
    private bool _isInitializing;
    private int _emitterSequence;

    public static AudioForgeRuntime Instance { get; private set; }
    public bool IsReady { get; private set; }
    public bool UseReferenceTimePreservingPitch { get { return useReferenceTimePreservingPitch; } }
    public bool IntegrateWithUnityAudioMixer { get { return integrateWithUnityAudioMixer; } }

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
        if (persistAcrossScenes)
        {
            DontDestroyOnLoad(gameObject);
        }
    }

    private void Update()
    {
        CleanupFinishedVoices();
    }

    public bool HasEvent(string eventId)
    {
        return _events.ContainsKey(eventId);
    }

    public bool HasBus(string busName)
    {
        return _buses.ContainsKey(NormalizeBusName(busName));
    }

    public bool HasGameParameter(string name)
    {
        return !string.IsNullOrWhiteSpace(name) && _gameParameterConfigs.ContainsKey(name.Trim());
    }

    public bool HasStateGroup(string groupName)
    {
        return !string.IsNullOrWhiteSpace(groupName) && _stateGroupConfigs.ContainsKey(groupName.Trim());
    }

    public bool HasSwitchGroup(string groupName)
    {
        return !string.IsNullOrWhiteSpace(groupName) && _switchGroupConfigs.ContainsKey(groupName.Trim());
    }

    public AudioForgeEmitterHandle RegisterEmitter(GameObject gameObject)
    {
        _emitterSequence += 1;
        string emitterId = "Emitter_" + _emitterSequence;
        var context = new AudioForgeEmitterContext
        {
            EmitterId = emitterId,
            BoundGameObject = gameObject,
        };
        _emitters[emitterId] = context;
        return new AudioForgeEmitterHandle { EmitterId = emitterId, BoundGameObject = gameObject };
    }

    public void UnregisterEmitter(AudioForgeEmitterHandle emitter)
    {
        if (emitter == null || string.IsNullOrWhiteSpace(emitter.EmitterId))
        {
            return;
        }

        _emitters.Remove(emitter.EmitterId);
    }

    public int GetRegisteredEventCount()
    {
        return _events.Count;
    }

    public int GetRegisteredBusCount()
    {
        return _buses.Count;
    }

    public List<string> GetEventIds()
    {
        List<string> eventIds = new List<string>(_events.Keys);
        eventIds.Sort(StringComparer.Ordinal);
        return eventIds;
    }

    public List<string> GetBusNames()
    {
        List<string> busNames = new List<string>(_buses.Keys);
        busNames.Sort(StringComparer.Ordinal);
        return busNames;
    }

    public string GetRuntimeAudioFormat()
    {
        return _runtimeAudioFormat;
    }

    public string GetResourceProviderName()
    {
        return _resourceProvider == null ? "Uninitialized" : _resourceProvider.GetType().Name;
    }

    public void SetGlobalGameParameter(string name, float value)
    {
        AudioForgeGameParameterConfig config;
        if (!TryGetGameParameterConfig(name, out config))
        {
            return;
        }

        _globalGameParameters[config.Name] = ClampGameParameterValue(config, value);
        RefreshBusVolumes(masterBusName);
    }

    public void SetGameParameter(string name, float value, AudioForgeEmitterHandle emitter)
    {
        AudioForgeGameParameterConfig config;
        AudioForgeEmitterContext context;
        if (!TryGetGameParameterConfig(name, out config) || !TryResolveEmitterContext(emitter, out context))
        {
            return;
        }

        context.LocalGameParameters[config.Name] = ClampGameParameterValue(config, value);
        RefreshBusVolumes(masterBusName);
    }

    public float GetGlobalGameParameter(string name)
    {
        AudioForgeGameParameterConfig config;
        if (!TryGetGameParameterConfig(name, out config))
        {
            return 0f;
        }

        float value;
        return _globalGameParameters.TryGetValue(config.Name, out value) ? value : config.DefaultValue;
    }

    public float GetGameParameter(string name, AudioForgeEmitterHandle emitter)
    {
        AudioForgeGameParameterConfig config;
        if (!TryGetGameParameterConfig(name, out config))
        {
            return 0f;
        }

        AudioForgeEmitterContext context;
        float value;
        if (TryResolveEmitterContext(emitter, out context) && context.LocalGameParameters.TryGetValue(config.Name, out value))
        {
            return value;
        }

        return GetGlobalGameParameter(config.Name);
    }

    public void SetState(string groupName, string stateName)
    {
        AudioForgeStateGroupConfig config;
        if (!TryGetStateGroupConfig(groupName, out config))
        {
            return;
        }

        _globalStates[config.Name] = string.IsNullOrWhiteSpace(stateName) ? config.DefaultState : stateName.Trim();
        RefreshBusVolumes(masterBusName);
    }

    public string GetState(string groupName)
    {
        AudioForgeStateGroupConfig config;
        if (!TryGetStateGroupConfig(groupName, out config))
        {
            return string.Empty;
        }

        string value;
        return _globalStates.TryGetValue(config.Name, out value) ? value : config.DefaultState;
    }

    public void SetSwitch(string groupName, string switchName, AudioForgeEmitterHandle emitter)
    {
        AudioForgeSwitchGroupConfig config;
        AudioForgeEmitterContext context;
        if (!TryGetSwitchGroupConfig(groupName, out config) || !TryResolveEmitterContext(emitter, out context))
        {
            return;
        }

        context.LocalSwitches[config.Name] = string.IsNullOrWhiteSpace(switchName) ? config.DefaultSwitch : switchName.Trim();
    }

    public string GetSwitch(string groupName, AudioForgeEmitterHandle emitter)
    {
        AudioForgeSwitchGroupConfig config;
        if (!TryGetSwitchGroupConfig(groupName, out config))
        {
            return string.Empty;
        }

        AudioForgeEmitterContext context;
        string value;
        if (TryResolveEmitterContext(emitter, out context) && context.LocalSwitches.TryGetValue(config.Name, out value))
        {
            return value;
        }

        return ResolveMappedSwitch(config, emitter);
    }

    /// <summary>
    /// 允许项目在初始化前注入自己的资源提供器，例如 Resources、Addressables 或 AssetBundle 版本。
    /// 传入 null 时，会回退到默认的 StreamingAssets 提供器。
    /// </summary>
    public void SetResourceProvider(IAudioForgeResourceProvider resourceProvider)
    {
        _resourceProviderOverride = resourceProvider;
        _clips.Clear();
        _processedClips.Clear();

        if (_resourceProviderOverride != null)
        {
            _resourceProvider = _resourceProviderOverride;
            return;
        }

        if (IsReady)
        {
            _resourceProvider = CreateDefaultResourceProvider();
        }
    }

    public float GetUnityMasterVolume()
    {
        return unityMasterVolume;
    }

    public float GetUnityEventVolumeOffsetDb(string eventId)
    {
        AudioForgeUnityEventVolumeBinding binding = FindUnityEventVolumeBinding(eventId);
        return binding != null ? binding.VolumeDbOffset : 0f;
    }

    public string GetMasterBusName()
    {
        return masterBusName;
    }

    public float GetBusVolume(string busName)
    {
        AudioForgeBusState busState;
        if (_buses.TryGetValue(NormalizeBusName(busName), out busState))
        {
            return busState.Volume;
        }

        return 1f;
    }

    public float GetUnityBusVolume(string busName)
    {
        AudioForgeBusState busState;
        if (_buses.TryGetValue(NormalizeBusName(busName), out busState))
        {
            return busState.UnityVolume;
        }

        AudioForgeUnityBusMixerBinding binding = FindUnityBusMixerBinding(busName);
        return binding != null ? Mathf.Clamp01(binding.Volume) : 1f;
    }

    public bool IsBusMuted(string busName)
    {
        AudioForgeBusState busState;
        if (_buses.TryGetValue(NormalizeBusName(busName), out busState))
        {
            return busState.IsMuted;
        }

        return false;
    }

    public string GetBusParentName(string busName)
    {
        AudioForgeBusState busState;
        if (_buses.TryGetValue(NormalizeBusName(busName), out busState))
        {
            return string.IsNullOrWhiteSpace(busState.ParentBusName) ? masterBusName : busState.ParentBusName;
        }

        return masterBusName;
    }

    public AudioMixerGroup GetBusOutputMixerGroup(string busName)
    {
        AudioForgeBusState busState;
        if (_buses.TryGetValue(NormalizeBusName(busName), out busState))
        {
            return busState.OutputMixerGroup;
        }

        return null;
    }

    public float GetEffectiveBusVolume(string busName)
    {
        return ComputeEffectiveVolume(1f, busName, (AudioForgeEmitterHandle)null);
    }

    public bool HasCustomBusMixerBinding(string busName)
    {
        return FindUnityBusMixerBinding(busName) != null;
    }

    public int GetActiveVoiceCount(string eventId)
    {
        AudioForgeRuntimeState state;
        if (_states.TryGetValue(eventId, out state))
        {
            return state.ActiveVoices.Count;
        }

        return 0;
    }

    public float GetEventBaseVolumeDb(string eventId)
    {
        AudioForgeEventConfig eventConfig;
        if (_events.TryGetValue(eventId, out eventConfig))
        {
            return eventConfig.VolumeDb;
        }

        return 0f;
    }

    public string GetEventBusName(string eventId)
    {
        AudioForgeEventConfig eventConfig;
        if (_events.TryGetValue(eventId, out eventConfig))
        {
            return NormalizeBusName(eventConfig.Bus);
        }

        return NormalizeBusName(null);
    }

    public int GetProcessedClipCacheCount()
    {
        return _processedClips.Count;
    }

    public List<AudioForgeDebugEventRecord> GetRecentDebugEventRecords()
    {
        return new List<AudioForgeDebugEventRecord>(_debugEventRecords);
    }

    public List<AudioForgeDebugBusRecord> GetRecentDebugBusRecords()
    {
        return new List<AudioForgeDebugBusRecord>(_debugBusRecords);
    }

    public Coroutine Play(string eventId)
    {
        return StartCoroutine(PlayEvent(eventId, null, null, 0f));
    }

    public Coroutine Play(string eventId, AudioSource overrideSource)
    {
        return StartCoroutine(PlayEvent(eventId, null, overrideSource, 0f));
    }

    public Coroutine Play(string eventId, AudioSource overrideSource, float localEventVolumeDbOffset)
    {
        return StartCoroutine(PlayEvent(eventId, null, overrideSource, localEventVolumeDbOffset));
    }

    public Coroutine Play(string eventId, AudioForgeEmitterHandle emitter)
    {
        return StartCoroutine(PlayEvent(eventId, emitter, null, 0f));
    }

    public Coroutine Play(string eventId, AudioForgeEmitterHandle emitter, AudioSource overrideSource, float localEventVolumeDbOffset)
    {
        return StartCoroutine(PlayEvent(eventId, emitter, overrideSource, localEventVolumeDbOffset));
    }

    public IEnumerator Initialize()
    {
        if (IsReady || _isInitializing)
        {
            yield break;
        }

        _isInitializing = true;
        ResetRuntimeData();

        // 参考运行时固定消费 StreamingAssets/AudioForge 下的导出契约，保持与文档和检查脚本一致。
        string jsonPath = Path.Combine(Application.streamingAssetsPath, "AudioForge", "AudioData.json");
        if (!File.Exists(jsonPath))
        {
            Debug.LogError("AudioData.json not found: " + jsonPath);
            _isInitializing = false;
            yield break;
        }

        string json = File.ReadAllText(jsonPath);
        AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
        _runtimeAudioFormat = string.IsNullOrWhiteSpace(database.RuntimeAudioFormat) ? "ogg" : database.RuntimeAudioFormat;
        _resourceProvider = _resourceProviderOverride ?? CreateDefaultResourceProvider();

        foreach (AudioForgeGameParameterConfig parameter in database.GameParameters)
        {
            if (parameter == null || string.IsNullOrWhiteSpace(parameter.Name))
            {
                continue;
            }
            parameter.Name = parameter.Name.Trim();
            _gameParameterConfigs[parameter.Name] = parameter;
            _globalGameParameters[parameter.Name] = ClampGameParameterValue(parameter, parameter.DefaultValue);
        }

        foreach (AudioForgeStateGroupConfig group in database.StateGroups)
        {
            if (group == null || string.IsNullOrWhiteSpace(group.Name))
            {
                continue;
            }
            group.Name = group.Name.Trim();
            _stateGroupConfigs[group.Name] = group;
            _globalStates[group.Name] = group.DefaultState;
        }

        foreach (AudioForgeSwitchGroupConfig group in database.SwitchGroups)
        {
            if (group == null || string.IsNullOrWhiteSpace(group.Name))
            {
                continue;
            }
            group.Name = group.Name.Trim();
            _switchGroupConfigs[group.Name] = group;
        }

        EnsureBus(masterBusName);
        foreach (AudioForgeBusConfig busConfig in database.BusConfigs)
        {
            AudioForgeBusState busState = EnsureBus(busConfig.Name);
            busState.ParentBusName = string.IsNullOrWhiteSpace(busConfig.ParentBus) ? masterBusName : NormalizeBusName(busConfig.ParentBus);
            if (busState.ParentBusName == busState.Name)
            {
                busState.ParentBusName = masterBusName;
            }
            if (busState.ParentBusName != masterBusName)
            {
                EnsureBus(busState.ParentBusName);
            }
            busState.Volume = Mathf.Max(0f, Mathf.Pow(10f, busConfig.VolumeDb / 20f));
            busState.IsMuted = busConfig.IsMuted;
            AppendDebugBusRecord(busState.Name, "init", busState.Volume, busState.IsMuted);
        }
        foreach (string busName in database.Buses)
        {
            EnsureBus(busName);
        }

        ApplyUnityMixerConfiguration();

        foreach (AudioForgeEventConfig eventConfig in database.Events)
        {
            if (eventConfig.DefaultClipIds.Count == 0)
            {
                foreach (AudioForgeClipConfig clip in eventConfig.Clips)
                {
                    if (clip != null && !string.IsNullOrEmpty(clip.ClipId))
                    {
                        eventConfig.DefaultClipIds.Add(clip.ClipId);
                    }
                }
            }
            _events[eventConfig.EventId] = eventConfig;
            _states[eventConfig.EventId] = new AudioForgeRuntimeState();
            EnsureBus(eventConfig.Bus);
        }

        PrewarmBusSources();
        IsReady = true;
        _isInitializing = false;
    }

    public IEnumerator PlayEvent(string eventId, AudioSource audioSource)
    {
        return PlayEvent(eventId, null, audioSource, 0f);
    }

    public IEnumerator PlayEvent(string eventId, AudioSource audioSource, float localEventVolumeDbOffset)
    {
        return PlayEvent(eventId, null, audioSource, localEventVolumeDbOffset);
    }

    public IEnumerator PlayEvent(string eventId, AudioForgeEmitterHandle emitter)
    {
        return PlayEvent(eventId, emitter, null, 0f);
    }

    public IEnumerator PlayEvent(string eventId, AudioForgeEmitterHandle emitter, AudioSource audioSource, float localEventVolumeDbOffset)
    {
        AudioForgeEventConfig eventConfig;
        if (!IsReady || !_events.TryGetValue(eventId, out eventConfig))
        {
            AppendDebugEventRecord(eventId, null, null, "rejected", "runtime_not_ready_or_event_missing", 0f, 0, 0, false, false);
            yield break;
        }

        AudioForgeEmitterContext emitterContext = null;
        TryResolveEmitterContext(emitter, out emitterContext);

        float now = Time.time;
        AudioForgeRuntimeState state = _states[eventId];
        CleanupStateVoices(state);
        if (now - state.LastTriggerTime < eventConfig.CooldownSeconds)
        {
            AppendDebugEventRecord(eventId, null, eventConfig.Bus, "rejected", "blocked_by_cooldown", 0f, 0, state.ComboStep, false, false);
            yield break;
        }

        if (eventConfig.MaxInstances > 0 && state.ActiveVoices.Count >= eventConfig.MaxInstances)
        {
            if (eventConfig.StealPolicy == "StopOldest" && state.ActiveVoices.Count > 0)
            {
                StopVoice(state.ActiveVoices[0]);
                CleanupStateVoices(state);
            }
            else
            {
                AppendDebugEventRecord(eventId, null, eventConfig.Bus, "rejected", "blocked_by_max_instances", 0f, 0, state.ComboStep, false, false);
                yield break;
            }
        }

        float resolvedVolumeDb = eventConfig.VolumeDb + GetUnityEventVolumeOffsetDb(eventId) + localEventVolumeDbOffset;
        int resolvedPitchCents = eventConfig.PitchCents;
        bool isMuted = false;
        ApplyActiveGameSyncEffects(emitter, ref resolvedVolumeDb, ref resolvedPitchCents, ref isMuted);
        ApplyStateOverrides(eventConfig.StateOverrides, ref resolvedVolumeDb, ref resolvedPitchCents, ref isMuted);
        ApplyRtpcBindings(eventConfig.RtpcBindings, emitter, ref resolvedVolumeDb, ref resolvedPitchCents);
        if (isMuted)
        {
            AppendDebugEventRecord(eventId, null, eventConfig.Bus, "rejected", "muted_by_state_override", resolvedVolumeDb, resolvedPitchCents, state.ComboStep, false, false);
            yield break;
        }

        AudioForgeClipConfig clipConfig = SelectClip(eventConfig, state, ResolveEventCandidateClips(eventConfig, emitter));
        if (clipConfig == null)
        {
            AppendDebugEventRecord(eventId, null, eventConfig.Bus, "rejected", "clip_selection_failed", 0f, 0, state.ComboStep, false, false);
            yield break;
        }

        object clip = null;
        yield return StartCoroutine(LoadClip(clipConfig.AssetKey, delegate(AudioClip loadedClip) { clip = loadedClip; }));
        AudioClip audioClip = clip as AudioClip;
        if (audioClip == null)
        {
            AppendDebugEventRecord(eventId, clipConfig, eventConfig.Bus, "rejected", "clip_load_failed", 0f, 0, state.ComboStep, false, false);
            yield break;
        }

        AudioForgeBusState busState = EnsureBus(eventConfig.Bus);
        AudioSource source = ResolvePlaybackSource(busState, audioSource);
        if (source == null)
        {
            Debug.LogWarning("AudioForgeRuntime could not acquire AudioSource for bus: " + busState.Name);
            AppendDebugEventRecord(eventId, clipConfig, busState.Name, "rejected", "no_available_audio_source", 0f, 0, state.ComboStep, false, false);
            yield break;
        }

        int comboStep = ResolveComboStep(eventConfig, state, now);
        float volumeDb = resolvedVolumeDb + RandomRange(eventConfig.VolumeRandMinDb, eventConfig.VolumeRandMaxDb);
        int pitchCents = resolvedPitchCents + RandomRangeInt(eventConfig.PitchRandMinCents, eventConfig.PitchRandMaxCents);
        if (eventConfig.PlayMode == "Combo")
        {
            pitchCents += comboStep * eventConfig.ComboPitchStepCents;
        }

        bool cacheHit = false;
        AudioClip playbackClip = ResolvePlaybackClip(clipConfig.AssetKey, audioClip, pitchCents, out cacheHit);
        bool usingReferencePitchClip = playbackClip != null && playbackClip != audioClip;
        if (playbackClip == null)
        {
            playbackClip = audioClip;
        }

        AudioForgeActiveVoice voice = new AudioForgeActiveVoice();
        voice.Source = source;
        voice.EventId = eventId;
        voice.EmitterId = emitterContext != null ? emitterContext.EmitterId : string.Empty;
        voice.BusName = busState.Name;
        voice.ManagedByPool = audioSource == null;
        voice.StartedAtTime = now;
        voice.BaseVolume = Mathf.Max(0f, Mathf.Pow(10f, volumeDb / 20f));
        voice.BasePitchCents = pitchCents;

        ConfigureSourceForPlayback(source, playbackClip, voice.BaseVolume, pitchCents, busState, usingReferencePitchClip, emitter);
        RegisterVoice(state, busState, voice);

        state.LastClipId = clipConfig.ClipId;
        state.LastTriggerTime = now;
        source.Play();
        AppendDebugEventRecord(eventId, clipConfig, busState.Name, "played", "ok", volumeDb, pitchCents, comboStep, usingReferencePitchClip, cacheHit);
    }

    public void SetBusVolume(string busName, float linearVolume)
    {
        AudioForgeBusState busState = EnsureBus(busName);
        busState.Volume = Mathf.Max(0f, linearVolume);
        RefreshBusVolumes(busState.Name);
        AppendDebugBusRecord(busState.Name, "set_volume", busState.Volume, busState.IsMuted);
    }

    public void SetBusMuted(string busName, bool isMuted)
    {
        AudioForgeBusState busState = EnsureBus(busName);
        busState.IsMuted = isMuted;
        RefreshBusVolumes(busState.Name);
        AppendDebugBusRecord(busState.Name, "set_muted", busState.Volume, busState.IsMuted);
    }

    public void SetUnityMasterVolume(float linearVolume)
    {
        unityMasterVolume = Mathf.Clamp01(linearVolume);
        RefreshBusVolumes(masterBusName);
        AppendDebugBusRecord(masterBusName, "set_unity_master_volume", unityMasterVolume, false);
    }

    public void SetUnityBusVolume(string busName, float linearVolume)
    {
        AudioForgeBusState busState = EnsureBus(busName);
        busState.UnityVolume = Mathf.Clamp01(linearVolume);

        AudioForgeUnityBusMixerBinding binding = FindUnityBusMixerBinding(busState.Name);
        if (binding == null)
        {
            binding = new AudioForgeUnityBusMixerBinding();
            binding.BusName = busState.Name;
            unityBusMixerBindings.Add(binding);
        }

        binding.Volume = busState.UnityVolume;
        RefreshBusVolumes(busState.Name);
        AppendDebugBusRecord(busState.Name, "set_unity_bus_volume", busState.UnityVolume, busState.IsMuted);
    }

    public void SetUnityEventVolumeOffsetDb(string eventId, float volumeDbOffset)
    {
        if (string.IsNullOrWhiteSpace(eventId))
        {
            return;
        }

        AudioForgeUnityEventVolumeBinding binding = FindUnityEventVolumeBinding(eventId);
        if (binding == null)
        {
            binding = new AudioForgeUnityEventVolumeBinding();
            binding.EventId = eventId.Trim();
            unityEventVolumeBindings.Add(binding);
        }

        binding.VolumeDbOffset = volumeDbOffset;
    }

    public void StopBus(string busName)
    {
        string normalizedBus = NormalizeBusName(busName);
        foreach (KeyValuePair<string, AudioForgeRuntimeState> pair in _states)
        {
            StopVoicesByBus(pair.Value, normalizedBus, true);
        }

        AudioForgeBusState busState;
        if (_buses.TryGetValue(normalizedBus, out busState))
        {
            CleanupBusState(busState);
        }
        AppendDebugBusRecord(normalizedBus, "stop_bus", GetBusVolume(normalizedBus), IsBusMuted(normalizedBus));
    }

    public void StopEvent(string eventId)
    {
        AudioForgeRuntimeState state;
        if (_states.TryGetValue(eventId, out state))
        {
            StopAllVoices(state);
            AppendDebugEventRecord(eventId, null, null, "stopped", "stop_event", 0f, 0, state.ComboStep, false, false);
        }
    }

    public void StopAllManagedVoices()
    {
        foreach (KeyValuePair<string, AudioForgeRuntimeState> pair in _states)
        {
            StopAllVoices(pair.Value);
        }
    }

    private void ResetRuntimeData()
    {
        StopAllManagedVoices();
        _events.Clear();
        _clips.Clear();
        foreach (KeyValuePair<string, AudioClip> pair in _processedClips)
        {
            if (pair.Value != null)
            {
                Destroy(pair.Value);
            }
        }
        _processedClips.Clear();
        _states.Clear();
        _gameParameterConfigs.Clear();
        _stateGroupConfigs.Clear();
        _switchGroupConfigs.Clear();
        _globalGameParameters.Clear();
        _globalStates.Clear();
        _emitters.Clear();
        _emitterSequence = 0;
        _debugEventRecords.Clear();
        _debugBusRecords.Clear();

        foreach (KeyValuePair<string, AudioForgeBusState> pair in _buses)
        {
            if (pair.Value.RootObject != null)
            {
                Destroy(pair.Value.RootObject);
            }
        }

        _buses.Clear();
        IsReady = false;
    }

    private void PrewarmBusSources()
    {
        foreach (KeyValuePair<string, AudioForgeBusState> pair in _buses)
        {
            AudioForgeBusState busState = pair.Value;
            int totalCount = busState.ActiveSources.Count + busState.IdleSources.Count;
            while (totalCount < prewarmedSourcesPerBus)
            {
                AudioSource source = CreateManagedSource(busState);
                ReleaseManagedSource(busState, source, false);
                totalCount += 1;
            }
        }
    }

    private AudioForgeBusState EnsureBus(string busName)
    {
        string normalizedBus = NormalizeBusName(busName);
        AudioForgeBusState busState;
        if (_buses.TryGetValue(normalizedBus, out busState))
        {
            return busState;
        }

        GameObject busRoot = new GameObject("Bus_" + normalizedBus);
        busRoot.transform.SetParent(transform, false);

        busState = new AudioForgeBusState();
        busState.Name = normalizedBus;
        busState.ParentBusName = masterBusName;
        busState.RootObject = busRoot;
        ApplyUnityMixerBinding(busState);
        _buses[normalizedBus] = busState;
        return busState;
    }

    private void ApplyUnityMixerConfiguration()
    {
        foreach (KeyValuePair<string, AudioForgeBusState> pair in _buses)
        {
            ApplyUnityMixerBinding(pair.Value);
        }
    }

    private void ApplyUnityMixerBinding(AudioForgeBusState busState)
    {
        if (busState == null)
        {
            return;
        }

        busState.UnityVolume = 1f;
        busState.OutputMixerGroup = null;

        if (!integrateWithUnityAudioMixer)
        {
            return;
        }

        busState.OutputMixerGroup = defaultOutputMixerGroup;
        AudioForgeUnityBusMixerBinding binding = FindUnityBusMixerBinding(busState.Name);
        if (binding != null)
        {
            if (binding.OutputMixerGroup != null)
            {
                busState.OutputMixerGroup = binding.OutputMixerGroup;
            }
            busState.UnityVolume = Mathf.Clamp01(binding.Volume);
        }
    }

    private AudioForgeUnityBusMixerBinding FindUnityBusMixerBinding(string busName)
    {
        string normalizedBusName = NormalizeBusName(busName);
        for (int index = 0; index < unityBusMixerBindings.Count; index += 1)
        {
            AudioForgeUnityBusMixerBinding binding = unityBusMixerBindings[index];
            if (binding != null && NormalizeBusName(binding.BusName) == normalizedBusName)
            {
                return binding;
            }
        }

        return null;
    }

    private AudioForgeUnityEventVolumeBinding FindUnityEventVolumeBinding(string eventId)
    {
        if (string.IsNullOrWhiteSpace(eventId))
        {
            return null;
        }

        string normalizedEventId = eventId.Trim();
        for (int index = 0; index < unityEventVolumeBindings.Count; index += 1)
        {
            AudioForgeUnityEventVolumeBinding binding = unityEventVolumeBindings[index];
            if (binding != null && string.Equals(binding.EventId, normalizedEventId, StringComparison.Ordinal))
            {
                return binding;
            }
        }

        return null;
    }

    private bool TryResolveEmitterContext(AudioForgeEmitterHandle emitter, out AudioForgeEmitterContext context)
    {
        return TryResolveEmitterContext(emitter != null ? emitter.EmitterId : string.Empty, out context);
    }

    private bool TryResolveEmitterContext(string emitterId, out AudioForgeEmitterContext context)
    {
        context = null;
        if (string.IsNullOrWhiteSpace(emitterId))
        {
            return false;
        }
        return _emitters.TryGetValue(emitterId, out context);
    }

    private bool TryGetGameParameterConfig(string name, out AudioForgeGameParameterConfig config)
    {
        config = null;
        return !string.IsNullOrWhiteSpace(name) && _gameParameterConfigs.TryGetValue(name.Trim(), out config);
    }

    private bool TryGetStateGroupConfig(string name, out AudioForgeStateGroupConfig config)
    {
        config = null;
        return !string.IsNullOrWhiteSpace(name) && _stateGroupConfigs.TryGetValue(name.Trim(), out config);
    }

    private bool TryGetSwitchGroupConfig(string name, out AudioForgeSwitchGroupConfig config)
    {
        config = null;
        return !string.IsNullOrWhiteSpace(name) && _switchGroupConfigs.TryGetValue(name.Trim(), out config);
    }

    private float ClampGameParameterValue(AudioForgeGameParameterConfig config, float value)
    {
        return config == null ? value : Mathf.Clamp(value, config.MinValue, config.MaxValue);
    }

    private string ResolveMappedSwitch(AudioForgeSwitchGroupConfig group, AudioForgeEmitterHandle emitter)
    {
        if (group == null)
        {
            return string.Empty;
        }
        if (group.UseGameParameter && !string.IsNullOrWhiteSpace(group.MappedGameParameter) && group.Thresholds.Count > 0)
        {
            float parameterValue = GetGameParameter(group.MappedGameParameter, emitter);
            for (int index = 0; index < group.Thresholds.Count; index += 1)
            {
                AudioForgeSwitchThresholdConfig threshold = group.Thresholds[index];
                if (threshold != null && parameterValue >= threshold.MinValue && parameterValue <= threshold.MaxValue)
                {
                    return threshold.SwitchName;
                }
            }
        }
        return group.DefaultSwitch;
    }

    private List<AudioForgeClipConfig> ResolveEventCandidateClips(AudioForgeEventConfig eventConfig, AudioForgeEmitterHandle emitter)
    {
        var clipsById = new Dictionary<string, AudioForgeClipConfig>();
        for (int index = 0; index < eventConfig.Clips.Count; index += 1)
        {
            AudioForgeClipConfig clip = eventConfig.Clips[index];
            if (clip != null && !string.IsNullOrEmpty(clip.ClipId))
            {
                clipsById[clip.ClipId] = clip;
            }
        }

        for (int index = 0; index < eventConfig.SwitchVariants.Count; index += 1)
        {
            AudioForgeSwitchVariantConfig variant = eventConfig.SwitchVariants[index];
            if (variant == null || string.IsNullOrWhiteSpace(variant.GroupName))
            {
                continue;
            }
            if (!string.Equals(GetSwitch(variant.GroupName, emitter), variant.SwitchName, StringComparison.Ordinal))
            {
                continue;
            }
            var matchedClips = new List<AudioForgeClipConfig>();
            for (int clipIndex = 0; clipIndex < variant.ClipIds.Count; clipIndex += 1)
            {
                AudioForgeClipConfig matchedClip;
                if (clipsById.TryGetValue(variant.ClipIds[clipIndex], out matchedClip))
                {
                    matchedClips.Add(matchedClip);
                }
            }
            if (matchedClips.Count > 0)
            {
                return matchedClips;
            }
        }

        var defaultClips = new List<AudioForgeClipConfig>();
        for (int index = 0; index < eventConfig.DefaultClipIds.Count; index += 1)
        {
            AudioForgeClipConfig clip;
            if (clipsById.TryGetValue(eventConfig.DefaultClipIds[index], out clip))
            {
                defaultClips.Add(clip);
            }
        }
        return defaultClips.Count > 0 ? defaultClips : new List<AudioForgeClipConfig>(eventConfig.Clips);
    }

    private void ApplyStateOverrides(List<AudioForgeStateOverrideConfig> overrides, ref float volumeDb, ref int pitchCents, ref bool isMuted)
    {
        for (int index = 0; index < overrides.Count; index += 1)
        {
            AudioForgeStateOverrideConfig item = overrides[index];
            if (item == null || string.IsNullOrWhiteSpace(item.GroupName))
            {
                continue;
            }
            if (!string.Equals(GetState(item.GroupName), item.StateName, StringComparison.Ordinal))
            {
                continue;
            }
            volumeDb += item.VolumeDb;
            pitchCents += item.PitchCents;
            isMuted = isMuted || item.IsMuted;
        }
    }

    private void ApplyActiveGameSyncEffects(AudioForgeEmitterHandle emitter, ref float volumeDb, ref int pitchCents, ref bool isMuted)
    {
        foreach (KeyValuePair<string, AudioForgeStateGroupConfig> pair in _stateGroupConfigs)
        {
            AudioForgeGameSyncEffectConfig effect = ResolveGameSyncEffect(pair.Value != null ? pair.Value.StateEffects : null, GetState(pair.Key));
            if (effect != null)
            {
                ApplyGameSyncEffect(effect, ref volumeDb, ref pitchCents, ref isMuted);
            }
        }

        foreach (KeyValuePair<string, AudioForgeSwitchGroupConfig> pair in _switchGroupConfigs)
        {
            AudioForgeGameSyncEffectConfig effect = ResolveGameSyncEffect(pair.Value != null ? pair.Value.SwitchEffects : null, GetSwitch(pair.Key, emitter));
            if (effect != null)
            {
                ApplyGameSyncEffect(effect, ref volumeDb, ref pitchCents, ref isMuted);
            }
        }
    }

    private static void ApplyGameSyncEffect(AudioForgeGameSyncEffectConfig effect, ref float volumeDb, ref int pitchCents, ref bool isMuted)
    {
        volumeDb += effect.VolumeDb;
        pitchCents += effect.PitchCents;
        isMuted = isMuted || effect.IsMuted;
    }

    private static AudioForgeGameSyncEffectConfig ResolveGameSyncEffect(List<AudioForgeGameSyncEffectConfig> effects, string valueName)
    {
        if (effects == null || string.IsNullOrWhiteSpace(valueName))
        {
            return null;
        }

        for (int index = 0; index < effects.Count; index += 1)
        {
            AudioForgeGameSyncEffectConfig effect = effects[index];
            if (effect != null && string.Equals(effect.ValueName, valueName, StringComparison.Ordinal))
            {
                return effect;
            }
        }

        return null;
    }

    private void ApplyRtpcBindings(List<AudioForgeRtpcBindingConfig> bindings, AudioForgeEmitterHandle emitter, ref float volumeDb, ref int pitchCents)
    {
        for (int index = 0; index < bindings.Count; index += 1)
        {
            AudioForgeRtpcBindingConfig binding = bindings[index];
            if (binding == null || string.IsNullOrWhiteSpace(binding.ParameterName))
            {
                continue;
            }
            float resolvedValue = EvaluateRtpcBinding(binding, emitter);
            if (string.Equals(binding.Target, "EventPitchCents", StringComparison.Ordinal))
            {
                pitchCents += Mathf.RoundToInt(resolvedValue);
            }
            else
            {
                volumeDb += resolvedValue;
            }
        }
    }

    private float EvaluateRtpcBinding(AudioForgeRtpcBindingConfig binding, AudioForgeEmitterHandle emitter)
    {
        float inputValue = string.Equals(binding.Scope, "Emitter", StringComparison.Ordinal)
            ? GetGameParameter(binding.ParameterName, emitter)
            : GetGlobalGameParameter(binding.ParameterName);
        return EvaluateCurve(binding.CurvePoints, inputValue);
    }

    private float EvaluateCurve(List<AudioForgeCurvePointConfig> points, float inputValue)
    {
        if (points == null || points.Count == 0)
        {
            return 0f;
        }
        if (points.Count == 1)
        {
            return points[0].OutputValue;
        }
        List<AudioForgeCurvePointConfig> ordered = new List<AudioForgeCurvePointConfig>(points);
        ordered.Sort(delegate(AudioForgeCurvePointConfig left, AudioForgeCurvePointConfig right) { return left.InputValue.CompareTo(right.InputValue); });
        if (inputValue <= ordered[0].InputValue)
        {
            return ordered[0].OutputValue;
        }
        for (int index = 0; index < ordered.Count - 1; index += 1)
        {
            AudioForgeCurvePointConfig current = ordered[index];
            AudioForgeCurvePointConfig next = ordered[index + 1];
            if (inputValue > next.InputValue)
            {
                continue;
            }
            if (string.Equals(current.Interpolation, "Constant", StringComparison.Ordinal))
            {
                return current.OutputValue;
            }
            float t = Mathf.InverseLerp(current.InputValue, next.InputValue, inputValue);
            return Mathf.Lerp(current.OutputValue, next.OutputValue, t);
        }
        return ordered[ordered.Count - 1].OutputValue;
    }

    private string NormalizeBusName(string busName)
    {
        return string.IsNullOrWhiteSpace(busName) ? "SFX" : busName.Trim();
    }

    /// <summary>
    /// 优先使用调用方传入的 AudioSource，否则从总线池中申请或新建托管声部。
    /// </summary>
    private AudioSource ResolvePlaybackSource(AudioForgeBusState busState, AudioSource overrideSource)
    {
        if (overrideSource != null)
        {
            return overrideSource;
        }

        CleanupBusState(busState);
        if (busState.IdleSources.Count > 0)
        {
            AudioSource pooledSource = busState.IdleSources.Dequeue();
            if (pooledSource != null)
            {
                if (!busState.ActiveSources.Contains(pooledSource))
                {
                    busState.ActiveSources.Add(pooledSource);
                }
                pooledSource.gameObject.SetActive(true);
                return pooledSource;
            }
        }

        int totalSourceCount = busState.ActiveSources.Count + busState.IdleSources.Count;
        if (totalSourceCount >= maxSourcesPerBus)
        {
            return null;
        }

        return CreateManagedSource(busState);
    }

    /// <summary>
    /// 创建受运行时托管的 AudioSource，生命周期由总线池负责回收。
    /// </summary>
    private AudioSource CreateManagedSource(AudioForgeBusState busState)
    {
        GameObject sourceObject = new GameObject("Source_" + busState.Name + "_" + (busState.ActiveSources.Count + busState.IdleSources.Count));
        sourceObject.transform.SetParent(busState.RootObject.transform, false);
        AudioSource source = sourceObject.AddComponent<AudioSource>();
        source.playOnAwake = false;
        if (integrateWithUnityAudioMixer && busState.OutputMixerGroup != null)
        {
            source.outputAudioMixerGroup = busState.OutputMixerGroup;
        }
        busState.ActiveSources.Add(source);
        return source;
    }

    /// <summary>
    /// 参考实现中的保时长变调入口。
    /// 默认按 资源键 + 音高 cents 缓存生成后的 AudioClip，避免重复处理。
    /// </summary>
    private AudioClip ResolvePlaybackClip(string assetKey, AudioClip sourceClip, int pitchCents, out bool cacheHit)
    {
        cacheHit = false;
        if (sourceClip == null || pitchCents == 0 || !useReferenceTimePreservingPitch)
        {
            return sourceClip;
        }

        string cacheKey = assetKey + "|pitch|" + pitchCents;
        AudioClip cachedClip;
        if (_processedClips.TryGetValue(cacheKey, out cachedClip) && cachedClip != null)
        {
            cacheHit = true;
            return cachedClip;
        }

        AudioClip generatedClip = AudioForgeTimePreservingPitchProcessor.CreatePitchShiftedClip(
            sourceClip,
            pitchCents,
            sourceClip.name + "_Pitch_" + pitchCents);

        if (generatedClip == null)
        {
            return sourceClip;
        }

        if (generatedClip != sourceClip)
        {
            _processedClips[cacheKey] = generatedClip;
        }

        return generatedClip;
    }

    private void AppendDebugEventRecord(
        string eventId,
        AudioForgeClipConfig clipConfig,
        string busName,
        string result,
        string message,
        float volumeDb,
        int pitchCents,
        int comboStep,
        bool usedTimePreservingPitch,
        bool cacheHit)
    {
        AudioForgeDebugEventRecord record = new AudioForgeDebugEventRecord();
        record.EventId = eventId ?? string.Empty;
        record.ClipId = clipConfig != null ? clipConfig.ClipId : string.Empty;
        record.AssetKey = clipConfig != null ? clipConfig.AssetKey : string.Empty;
        record.BusName = busName ?? string.Empty;
        record.Result = result;
        record.Message = message;
        record.TrimStartMs = clipConfig != null ? clipConfig.TrimStartMs : 0;
        record.TrimEndMs = clipConfig != null ? clipConfig.TrimEndMs : 0;
        record.FadeInMs = clipConfig != null ? clipConfig.FadeInMs : 0;
        record.FadeOutMs = clipConfig != null ? clipConfig.FadeOutMs : 0;
        record.LoopStartMs = clipConfig != null ? clipConfig.LoopStartMs : 0;
        record.LoopEndMs = clipConfig != null ? clipConfig.LoopEndMs : 0;
        record.VolumeDb = volumeDb;
        record.PitchCents = pitchCents;
        record.ComboStep = comboStep;
        record.UsedTimePreservingPitch = usedTimePreservingPitch;
        record.CacheHit = cacheHit;
        record.Timestamp = Time.time;
        _debugEventRecords.Insert(0, record);
        if (_debugEventRecords.Count > MaxDebugEventRecords)
        {
            _debugEventRecords.RemoveAt(_debugEventRecords.Count - 1);
        }
    }

    private void AppendDebugBusRecord(string busName, string action, float volume, bool isMuted)
    {
        AudioForgeDebugBusRecord record = new AudioForgeDebugBusRecord();
        record.BusName = busName ?? string.Empty;
        record.Action = action;
        record.Volume = volume;
        record.IsMuted = isMuted;
        record.Timestamp = Time.time;
        _debugBusRecords.Insert(0, record);
        if (_debugBusRecords.Count > MaxDebugBusRecords)
        {
            _debugBusRecords.RemoveAt(_debugBusRecords.Count - 1);
        }
    }

    /// <summary>
    /// 将最终 Clip、音量和音高应用到 AudioSource。
    /// 如果已经使用了保时长变调后的参考 Clip，这里保持 pitch 为 1。
    /// </summary>
    private void ConfigureSourceForPlayback(AudioSource source, AudioClip audioClip, float baseVolume, int pitchCents, AudioForgeBusState busState, bool usingReferencePitchClip, AudioForgeEmitterHandle emitter)
    {
        source.clip = audioClip;
        source.pitch = usingReferencePitchClip ? 1f : Mathf.Pow(2f, pitchCents / 1200f);
        source.loop = false;
        source.spatialBlend = 0f;
        if (integrateWithUnityAudioMixer && busState.OutputMixerGroup != null)
        {
            source.outputAudioMixerGroup = busState.OutputMixerGroup;
        }
        source.volume = ComputeEffectiveVolume(baseVolume, busState.Name, emitter);
    }

    private void RegisterVoice(AudioForgeRuntimeState state, AudioForgeBusState busState, AudioForgeActiveVoice voice)
    {
        if (!busState.ActiveSources.Contains(voice.Source))
        {
            busState.ActiveSources.Add(voice.Source);
        }

        state.ActiveVoices.Add(voice);
    }

    /// <summary>
    /// 统一处理 Random / Sequence / Combo 的片段选择。
    /// Combo 当前只改变音高步进，不改变选片语义。
    /// </summary>
    private AudioForgeClipConfig SelectClip(AudioForgeEventConfig eventConfig, AudioForgeRuntimeState state, List<AudioForgeClipConfig> availableClips)
    {
        if (availableClips == null || availableClips.Count == 0)
        {
            return null;
        }

        if (eventConfig.PlayMode == "Sequence")
        {
            int index = state.SequenceIndex % availableClips.Count;
            state.SequenceIndex = (index + 1) % availableClips.Count;
            return availableClips[index];
        }

        List<AudioForgeClipConfig> candidates = new List<AudioForgeClipConfig>(availableClips);
        if (eventConfig.AvoidImmediateRepeat && !string.IsNullOrEmpty(state.LastClipId) && candidates.Count > 1)
        {
            candidates.RemoveAll(delegate(AudioForgeClipConfig clip) { return clip.ClipId == state.LastClipId; });
            if (candidates.Count == 0)
            {
                candidates = new List<AudioForgeClipConfig>(availableClips);
            }
        }

        int totalWeight = 0;
        foreach (AudioForgeClipConfig candidate in candidates)
        {
            totalWeight += Mathf.Max(1, candidate.Weight);
        }

        int pick = _random.Next(0, totalWeight);
        int cumulative = 0;
        foreach (AudioForgeClipConfig candidate in candidates)
        {
            cumulative += Mathf.Max(1, candidate.Weight);
            if (pick < cumulative)
            {
                return candidate;
            }
        }

        return candidates[candidates.Count - 1];
    }

    /// <summary>
    /// 通过资源提供器加载原始导出 Clip，并对原始文件做缓存。
    /// 生产版可直接替换 _resourceProvider，而不必改动播放主流程。
    /// </summary>
    private IEnumerator LoadClip(string assetKey, System.Action<AudioClip> onLoaded)
    {
        AudioClip cachedClip;
        if (_clips.TryGetValue(assetKey, out cachedClip))
        {
            onLoaded(cachedClip);
            yield break;
        }

        if (_resourceProvider == null)
        {
            Debug.LogError("AudioForge resource provider is null.");
            onLoaded(null);
            yield break;
        }

        object loadedClip = null;
        yield return StartCoroutine(_resourceProvider.LoadClip(assetKey, _runtimeAudioFormat, delegate(AudioClip clip) { loadedClip = clip; }));
        AudioClip clip = loadedClip as AudioClip;
        if (clip == null)
        {
            onLoaded(null);
            yield break;
        }

        _clips[assetKey] = clip;
        onLoaded(clip);
    }

    private IAudioForgeResourceProvider CreateDefaultResourceProvider()
    {
        string assetsRoot = Path.Combine(Application.streamingAssetsPath, "AudioForge", "Assets");
        return new AudioForgeStreamingAssetsProvider(assetsRoot);
    }

    private void CleanupFinishedVoices()
    {
        foreach (KeyValuePair<string, AudioForgeRuntimeState> pair in _states)
        {
            CleanupStateVoices(pair.Value);
        }

        foreach (KeyValuePair<string, AudioForgeBusState> pair in _buses)
        {
            CleanupBusState(pair.Value);
        }
    }

    private void CleanupStateVoices(AudioForgeRuntimeState state)
    {
        for (int index = state.ActiveVoices.Count - 1; index >= 0; index -= 1)
        {
            AudioForgeActiveVoice voice = state.ActiveVoices[index];
            if (voice == null || voice.Source == null)
            {
                state.ActiveVoices.RemoveAt(index);
                continue;
            }

            if (voice.Source.isPlaying)
            {
                voice.Source.volume = ComputeEffectiveVolume(voice.BaseVolume, voice.BusName, voice.EmitterId);
                continue;
            }

            AudioForgeBusState busState = null;
            if (_buses.TryGetValue(voice.BusName, out busState) && voice.ManagedByPool)
            {
                ReleaseManagedSource(busState, voice.Source, false);
            }
            else if (busState != null)
            {
                busState.ActiveSources.Remove(voice.Source);
            }

            state.ActiveVoices.RemoveAt(index);
        }
    }

    private void CleanupBusState(AudioForgeBusState busState)
    {
        for (int index = busState.ActiveSources.Count - 1; index >= 0; index -= 1)
        {
            AudioSource source = busState.ActiveSources[index];
            if (source == null)
            {
                busState.ActiveSources.RemoveAt(index);
                continue;
            }

            if (!source.isPlaying && source.transform.parent == busState.RootObject.transform)
            {
                ReleaseManagedSource(busState, source, false);
            }
        }
    }

    private void ReleaseManagedSource(AudioForgeBusState busState, AudioSource source, bool stopPlayback)
    {
        if (source == null)
        {
            return;
        }

        if (stopPlayback)
        {
            source.Stop();
        }

        source.clip = null;
        source.pitch = 1f;
        source.volume = 0f;
        source.gameObject.SetActive(false);
        busState.ActiveSources.Remove(source);
        if (source.transform.parent == busState.RootObject.transform)
        {
            busState.IdleSources.Enqueue(source);
        }
    }

    private void StopVoice(AudioForgeActiveVoice voice)
    {
        if (voice == null || voice.Source == null)
        {
            return;
        }

        AudioForgeBusState busState = null;
        _buses.TryGetValue(voice.BusName, out busState);
        if (voice.ManagedByPool && busState != null)
        {
            ReleaseManagedSource(busState, voice.Source, true);
            return;
        }

        voice.Source.Stop();
        if (busState != null)
        {
            busState.ActiveSources.Remove(voice.Source);
        }
    }

    private void StopVoicesByBus(AudioForgeRuntimeState state, string busName, bool includeDescendants)
    {
        for (int index = state.ActiveVoices.Count - 1; index >= 0; index -= 1)
        {
            AudioForgeActiveVoice voice = state.ActiveVoices[index];
            if (voice == null || !IsBusAffectedByRoute(voice.BusName, busName, includeDescendants))
            {
                continue;
            }

            StopVoice(voice);
            state.ActiveVoices.RemoveAt(index);
        }
    }

    private void StopAllVoices(AudioForgeRuntimeState state)
    {
        for (int index = state.ActiveVoices.Count - 1; index >= 0; index -= 1)
        {
            StopVoice(state.ActiveVoices[index]);
        }
        state.ActiveVoices.Clear();
    }

    private void RefreshBusVolumes(string busName)
    {
        foreach (KeyValuePair<string, AudioForgeRuntimeState> pair in _states)
        {
            AudioForgeRuntimeState state = pair.Value;
            for (int index = 0; index < state.ActiveVoices.Count; index += 1)
            {
                AudioForgeActiveVoice voice = state.ActiveVoices[index];
                if (voice != null && voice.Source != null && IsBusAffectedByRoute(voice.BusName, busName, true))
                {
                    voice.Source.volume = ComputeEffectiveVolume(voice.BaseVolume, voice.BusName, voice.EmitterId);
                }
            }
        }
    }

    private bool IsBusAffectedByRoute(string voiceBusName, string targetBusName, bool includeDescendants)
    {
        string normalizedVoiceBus = NormalizeBusName(voiceBusName);
        string normalizedTargetBus = NormalizeBusName(targetBusName);
        if (!includeDescendants)
        {
            return normalizedVoiceBus == normalizedTargetBus;
        }

        string currentBus = normalizedVoiceBus;
        HashSet<string> visited = new HashSet<string>();
        while (true)
        {
            if (currentBus == normalizedTargetBus)
            {
                return true;
            }

            if (currentBus == masterBusName || !visited.Add(currentBus))
            {
                return false;
            }

            AudioForgeBusState busState;
            if (!_buses.TryGetValue(currentBus, out busState))
            {
                return false;
            }

            currentBus = string.IsNullOrWhiteSpace(busState.ParentBusName) ? masterBusName : NormalizeBusName(busState.ParentBusName);
        }
    }

    private float ComputeEffectiveVolume(float baseVolume, string busName, string emitterId)
    {
        AudioForgeEmitterContext emitterContext = null;
        TryResolveEmitterContext(emitterId, out emitterContext);
        return ComputeEffectiveVolume(
            baseVolume,
            busName,
            emitterContext != null ? new AudioForgeEmitterHandle { EmitterId = emitterContext.EmitterId, BoundGameObject = emitterContext.BoundGameObject } : null
        );
    }

    private float ComputeEffectiveVolume(float baseVolume, string busName, AudioForgeEmitterHandle emitter)
    {
        float gain = baseVolume * Mathf.Clamp01(unityMasterVolume);
        string currentBus = NormalizeBusName(busName);
        HashSet<string> visited = new HashSet<string>();
        while (true)
        {
            AudioForgeBusState busState;
            if (!_buses.TryGetValue(currentBus, out busState))
            {
                break;
            }

            float volumeDbOffset = 0f;
            int unusedPitchCents = 0;
            bool isMuted = busState.IsMuted;
            ApplyStateOverrides(busState.StateOverrides, ref volumeDbOffset, ref unusedPitchCents, ref isMuted);
            ApplyRtpcBindings(busState.RtpcBindings, emitter, ref volumeDbOffset, ref unusedPitchCents);
            if (isMuted)
            {
                return 0f;
            }

            gain *= busState.Volume;
            gain *= Mathf.Max(0f, Mathf.Pow(10f, volumeDbOffset / 20f));
            gain *= Mathf.Clamp01(busState.UnityVolume);
            if (currentBus == masterBusName)
            {
                break;
            }

            if (!visited.Add(currentBus))
            {
                return 0f;
            }

            currentBus = string.IsNullOrWhiteSpace(busState.ParentBusName) ? masterBusName : NormalizeBusName(busState.ParentBusName);
        }

        return Mathf.Max(0f, gain);
    }

    private int ResolveComboStep(AudioForgeEventConfig eventConfig, AudioForgeRuntimeState state, float now)
    {
        if (eventConfig.PlayMode != "Combo")
        {
            state.ComboStep = 0;
            return 0;
        }

        if (now - state.LastTriggerTime > eventConfig.ComboResetSeconds)
        {
            state.ComboStep = 0;
        }
        else
        {
            state.ComboStep += 1;
        }

        if (eventConfig.ComboMaxStep > 0)
        {
            state.ComboStep = Mathf.Min(state.ComboStep, eventConfig.ComboMaxStep);
        }

        return state.ComboStep;
    }

    private float RandomRange(float min, float max)
    {
        if (Mathf.Approximately(min, max))
        {
            return min;
        }
        return Mathf.Lerp(min, max, (float)_random.NextDouble());
    }

    private int RandomRangeInt(int min, int max)
    {
        if (min == max)
        {
            return min;
        }
        return Mathf.RoundToInt(RandomRange(min, max));
    }
}
