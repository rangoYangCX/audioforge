using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class AudioForgeValidationRunner
{
    private const string MenuPath = "AudioForge/Validation/Run Active Scene Validation";

    [MenuItem(MenuPath)]
    public static void RunActiveSceneValidation()
    {
        AudioForgeValidationReport report = BuildReport();
        WriteReportFiles(report);
        LogSummary(report);
    }

    /// <summary>
    /// 按“资源布局 -> 场景绑定 -> Runtime 初始化”顺序构建一份验证报告。
    /// 这份工具的目标是给 Unity 开发和联调同学一个固定的自检入口。
    /// </summary>
    private static AudioForgeValidationReport BuildReport()
    {
        AudioForgeValidationReport report = new AudioForgeValidationReport();
        report.GeneratedAtUtc = DateTime.UtcNow.ToString("o");
        report.ProjectRoot = Directory.GetParent(Application.dataPath).FullName;
        report.ScenePath = SceneManager.GetActiveScene().path;

        AudioForgeDatabase database = null;
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, "AudioForge", "AudioData.json");
        string assetsRoot = Path.Combine(Application.streamingAssetsPath, "AudioForge", "Assets");

        report.Checks.Add(CheckStreamingAssetsLayout(audioDataPath, assetsRoot, ref database));
        report.Checks.Add(CheckRuntimeAssetFiles(assetsRoot, database));
        report.Checks.Add(CheckSceneMissingScripts());
        report.Checks.Add(CheckSceneBindings(database));
        report.Checks.Add(CheckRuntimeInitialization(database));
        report.Checks.Add(CheckRuntimeGameSyncSmoke(database));

        report.Passed = true;
        for (int index = 0; index < report.Checks.Count; index += 1)
        {
            if (!report.Checks[index].Passed)
            {
                report.Passed = false;
                break;
            }
        }

        return report;
    }

    private static AudioForgeValidationCheck CheckStreamingAssetsLayout(string audioDataPath, string assetsRoot, ref AudioForgeDatabase database)
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "streaming_assets_layout";
        check.Passed = true;
        check.Details.Add("audio_data_path=" + audioDataPath);
        check.Details.Add("assets_root=" + assetsRoot);

        if (!File.Exists(audioDataPath))
        {
            check.Passed = false;
            check.Details.Add("missing_audio_data_json");
            return check;
        }

        if (!Directory.Exists(assetsRoot))
        {
            check.Passed = false;
            check.Details.Add("missing_runtime_assets_directory");
            return check;
        }

        try
        {
            string json = File.ReadAllText(audioDataPath);
            database = AudioForgeJsonAdapter.Parse(json);
            check.Details.Add("schema_version=" + database.SchemaVersion);
            check.Details.Add("runtime_audio_format=" + database.RuntimeAudioFormat);
            check.Details.Add("event_count=" + database.Events.Count);
            check.Details.Add("bus_count=" + database.Buses.Count);
        }
        catch (Exception ex)
        {
            check.Passed = false;
            check.Details.Add("parse_error=" + ex.Message);
        }

        return check;
    }

    private static AudioForgeValidationCheck CheckRuntimeAssetFiles(string assetsRoot, AudioForgeDatabase database)
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "runtime_asset_files";
        check.Passed = true;

        if (database == null)
        {
            check.Passed = false;
            check.Details.Add("database_unavailable");
            return check;
        }

        string runtimeFormat = string.IsNullOrEmpty(database.RuntimeAudioFormat) ? "ogg" : database.RuntimeAudioFormat;
        int clipCount = 0;
        for (int eventIndex = 0; eventIndex < database.Events.Count; eventIndex += 1)
        {
            AudioForgeEventConfig eventConfig = database.Events[eventIndex];
            for (int clipIndex = 0; clipIndex < eventConfig.Clips.Count; clipIndex += 1)
            {
                AudioForgeClipConfig clipConfig = eventConfig.Clips[clipIndex];
                clipCount += 1;
                string runtimePath = Path.Combine(assetsRoot, clipConfig.AssetKey + "." + runtimeFormat);
                string wavFallbackPath = Path.Combine(assetsRoot, clipConfig.AssetKey + ".wav");
                if (!File.Exists(runtimePath) && !File.Exists(wavFallbackPath))
                {
                    check.Passed = false;
                    check.Details.Add("missing_clip=" + clipConfig.AssetKey);
                }
            }
        }

        check.Details.Add("clip_count=" + clipCount);
        return check;
    }

    private static AudioForgeValidationCheck CheckSceneMissingScripts()
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "scene_missing_scripts";
        check.Passed = true;

        Scene scene = SceneManager.GetActiveScene();
        if (!scene.IsValid())
        {
            check.Passed = false;
            check.Details.Add("invalid_active_scene");
            return check;
        }

        GameObject[] roots = scene.GetRootGameObjects();
        int missingCount = 0;
        for (int index = 0; index < roots.Length; index += 1)
        {
            missingCount += CountMissingScriptsRecursive(roots[index], check.Details);
        }

        if (missingCount > 0)
        {
            check.Passed = false;
        }
        check.Details.Add("missing_script_count=" + missingCount);
        return check;
    }

    private static AudioForgeValidationCheck CheckSceneBindings(AudioForgeDatabase database)
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "scene_bindings";
        check.Passed = true;

        Scene scene = SceneManager.GetActiveScene();
        if (!scene.IsValid())
        {
            check.Passed = false;
            check.Details.Add("invalid_active_scene");
            return check;
        }

        Dictionary<string, bool> eventIds = new Dictionary<string, bool>();
        if (database != null)
        {
            for (int index = 0; index < database.Events.Count; index += 1)
            {
                eventIds[database.Events[index].EventId] = true;
            }
        }

        int runtimeCount = 0;
        int bootstrapCount = 0;
        int eventPlayerCount = 0;
        GameObject[] roots = scene.GetRootGameObjects();
        for (int index = 0; index < roots.Length; index += 1)
        {
            AudioForgeRuntime[] runtimes = roots[index].GetComponentsInChildren<AudioForgeRuntime>(true);
            AudioForgeBootstrap[] bootstraps = roots[index].GetComponentsInChildren<AudioForgeBootstrap>(true);
            AudioForgeEventPlayer[] eventPlayers = roots[index].GetComponentsInChildren<AudioForgeEventPlayer>(true);
            runtimeCount += runtimes.Length;
            bootstrapCount += bootstraps.Length;
            eventPlayerCount += eventPlayers.Length;

            ValidateBootstrapBindings(bootstraps, eventIds, check);
            ValidateEventPlayerBindings(eventPlayers, eventIds, check);
        }

        if (runtimeCount == 0 && bootstrapCount == 0)
        {
            check.Passed = false;
            check.Details.Add("no_runtime_or_bootstrap_found_in_scene");
        }

        check.Details.Add("runtime_count=" + runtimeCount);
        check.Details.Add("bootstrap_count=" + bootstrapCount);
        check.Details.Add("event_player_count=" + eventPlayerCount);
        return check;
    }

    private static AudioForgeValidationCheck CheckRuntimeInitialization(AudioForgeDatabase database)
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "runtime_initialization";
        check.Passed = true;

        if (database == null)
        {
            check.Passed = false;
            check.Details.Add("database_unavailable");
            return check;
        }

        GameObject runtimeRoot = new GameObject("AudioForgeValidationRuntimeTemp");
        runtimeRoot.hideFlags = HideFlags.HideAndDontSave;
        AudioForgeRuntime runtime = runtimeRoot.AddComponent<AudioForgeRuntime>();

        try
        {
            IEnumerator routine = runtime.Initialize();
            while (routine.MoveNext())
            {
            }

            if (!runtime.IsReady)
            {
                check.Passed = false;
                check.Details.Add("runtime_not_ready_after_initialize");
            }
            else
            {
                check.Details.Add("runtime_initialized");
            }

            for (int index = 0; index < database.Events.Count; index += 1)
            {
                if (!runtime.HasEvent(database.Events[index].EventId))
                {
                    check.Passed = false;
                    check.Details.Add("runtime_missing_event=" + database.Events[index].EventId);
                }
            }

            for (int index = 0; index < database.Buses.Count; index += 1)
            {
                if (!runtime.HasBus(database.Buses[index]))
                {
                    check.Passed = false;
                    check.Details.Add("runtime_missing_bus=" + database.Buses[index]);
                }
            }
        }
        catch (Exception ex)
        {
            check.Passed = false;
            check.Details.Add("runtime_exception=" + ex.Message);
        }
        finally
        {
            if (runtimeRoot != null)
            {
                UnityEngine.Object.DestroyImmediate(runtimeRoot);
            }
        }

        return check;
    }

    private static AudioForgeValidationCheck CheckRuntimeGameSyncSmoke(AudioForgeDatabase database)
    {
        AudioForgeValidationCheck check = new AudioForgeValidationCheck();
        check.Name = "runtime_gamesync_smoke";
        check.Passed = true;

        if (database == null)
        {
            check.Passed = false;
            check.Details.Add("database_unavailable");
            return check;
        }

        if (database.SchemaVersion < 2)
        {
            check.Details.Add("skipped_schema_version=" + database.SchemaVersion);
            return check;
        }

        if (database.GameParameters.Count == 0 && database.StateGroups.Count == 0 && database.SwitchGroups.Count == 0)
        {
            check.Details.Add("skipped_no_gamesync_definitions");
            return check;
        }

        GameObject runtimeRoot = new GameObject("AudioForgeValidationGameSyncRuntimeTemp");
        runtimeRoot.hideFlags = HideFlags.HideAndDontSave;
        AudioForgeRuntime runtime = runtimeRoot.AddComponent<AudioForgeRuntime>();
        GameObject emitterObject = new GameObject("AudioForgeValidationEmitterTemp");
        emitterObject.hideFlags = HideFlags.HideAndDontSave;

        try
        {
            RunEnumerator(runtime.Initialize());
            if (!runtime.IsReady)
            {
                check.Passed = false;
                check.Details.Add("runtime_not_ready_for_gamesync_smoke");
                return check;
            }

            for (int index = 0; index < database.GameParameters.Count; index += 1)
            {
                if (!runtime.HasGameParameter(database.GameParameters[index].Name))
                {
                    check.Passed = false;
                    check.Details.Add("missing_game_parameter=" + database.GameParameters[index].Name);
                }
            }

            for (int index = 0; index < database.StateGroups.Count; index += 1)
            {
                if (!runtime.HasStateGroup(database.StateGroups[index].Name))
                {
                    check.Passed = false;
                    check.Details.Add("missing_state_group=" + database.StateGroups[index].Name);
                }
            }

            for (int index = 0; index < database.SwitchGroups.Count; index += 1)
            {
                if (!runtime.HasSwitchGroup(database.SwitchGroups[index].Name))
                {
                    check.Passed = false;
                    check.Details.Add("missing_switch_group=" + database.SwitchGroups[index].Name);
                }
            }

            AudioForgeEmitterHandle emitter = runtime.RegisterEmitter(emitterObject);
            if (emitter == null || string.IsNullOrEmpty(emitter.EmitterId))
            {
                check.Passed = false;
                check.Details.Add("failed_to_register_emitter");
                return check;
            }
            check.Details.Add("registered_emitter=" + emitter.EmitterId);

            if (database.GameParameters.Count > 0)
            {
                AudioForgeGameParameterConfig parameter = database.GameParameters[0];
                runtime.SetGlobalGameParameter(parameter.Name, parameter.MaxValue);
                runtime.SetGameParameter(parameter.Name, parameter.MinValue, emitter);
                float emitterValue = runtime.GetGameParameter(parameter.Name, emitter);
                if (Mathf.Abs(emitterValue - parameter.MinValue) > 0.001f)
                {
                    check.Passed = false;
                    check.Details.Add("emitter_parameter_mismatch=" + parameter.Name + ":" + emitterValue);
                }
                else
                {
                    check.Details.Add("emitter_parameter_ok=" + parameter.Name + ":" + emitterValue.ToString("F2"));
                }
            }

            if (database.StateGroups.Count > 0)
            {
                AudioForgeStateGroupConfig group = database.StateGroups[0];
                string targetState = !string.IsNullOrEmpty(group.DefaultState)
                    ? group.DefaultState
                    : (group.States.Count > 0 ? group.States[group.States.Count - 1] : string.Empty);
                if (!string.IsNullOrEmpty(targetState))
                {
                    runtime.SetState(group.Name, targetState);
                    string resolvedState = runtime.GetState(group.Name);
                    if (!string.Equals(resolvedState, targetState, StringComparison.Ordinal))
                    {
                        check.Passed = false;
                        check.Details.Add("state_roundtrip_failed=" + group.Name + ":" + resolvedState);
                    }
                    else
                    {
                        check.Details.Add("state_roundtrip_ok=" + group.Name + ":" + resolvedState);
                    }
                }
            }

            VerifyStateChildEffects(database, runtime, emitter, check);
            VerifySwitchChildEffects(database, runtime, emitter, check);

            AudioForgeEventConfig switchEvent = FindSwitchVariantEvent(database);
            if (switchEvent == null)
            {
                check.Details.Add("switch_variant_event_not_found");
            }
            else
            {
                AudioForgeSwitchVariantConfig variant = switchEvent.SwitchVariants[0];
                runtime.SetSwitch(variant.GroupName, variant.SwitchName, emitter);
                string resolvedSwitch = runtime.GetSwitch(variant.GroupName, emitter);
                if (!string.Equals(resolvedSwitch, variant.SwitchName, StringComparison.Ordinal))
                {
                    check.Passed = false;
                    check.Details.Add("switch_roundtrip_failed=" + variant.GroupName + ":" + resolvedSwitch);
                }
                else
                {
                    check.Details.Add("switch_roundtrip_ok=" + variant.GroupName + ":" + resolvedSwitch);
                }

                AudioForgeDebugEventRecord latestRecord = PlayAndGetLatestRecord(runtime, switchEvent, emitter);
                if (latestRecord == null)
                {
                    check.Passed = false;
                    check.Details.Add("switch_event_no_debug_record=" + switchEvent.EventId);
                }
                else if (!string.Equals(latestRecord.Result, "played", StringComparison.Ordinal))
                {
                    check.Passed = false;
                    check.Details.Add("switch_event_failed=" + switchEvent.EventId + ":" + latestRecord.Message);
                }
                else if (!variant.ClipIds.Contains(latestRecord.ClipId))
                {
                    check.Passed = false;
                    check.Details.Add("switch_variant_mismatch=" + switchEvent.EventId + ":" + latestRecord.ClipId);
                }
                else
                {
                    check.Details.Add("switch_variant_played=" + switchEvent.EventId + ":" + latestRecord.ClipId);
                }
            }
        }
        catch (Exception ex)
        {
            check.Passed = false;
            check.Details.Add("gamesync_smoke_exception=" + ex.Message);
        }
        finally
        {
            if (emitterObject != null)
            {
                UnityEngine.Object.DestroyImmediate(emitterObject);
            }
            if (runtimeRoot != null)
            {
                UnityEngine.Object.DestroyImmediate(runtimeRoot);
            }
        }

        return check;
    }

    private static void VerifyStateChildEffects(AudioForgeDatabase database, AudioForgeRuntime runtime, AudioForgeEmitterHandle emitter, AudioForgeValidationCheck check)
    {
        AudioForgeStateGroupConfig group = FindStateEffectGroup(database);
        if (group == null)
        {
            check.Details.Add("state_child_effects_skipped");
            return;
        }

        AudioForgeGameSyncEffectConfig targetEffect = FindMeaningfulEffect(group.StateEffects);
        string baselineState = ResolveAlternateValue(group.States, targetEffect != null ? targetEffect.ValueName : string.Empty, group.DefaultState);
        AudioForgeEventConfig eventConfig = FindPlayableEventWithoutStateOverride(database, group.Name);
        if (targetEffect == null || string.IsNullOrEmpty(baselineState) || eventConfig == null)
        {
            check.Details.Add("state_child_effects_incomplete");
            return;
        }

        AudioForgeGameSyncEffectConfig baselineEffect = FindEffect(group.StateEffects, baselineState);
        runtime.SetState(group.Name, baselineState);
        AudioForgeDebugEventRecord baselineRecord = PlayAndGetLatestRecord(runtime, eventConfig, emitter);
        runtime.SetState(group.Name, targetEffect.ValueName);
        AudioForgeDebugEventRecord effectRecord = PlayAndGetLatestRecord(runtime, eventConfig, emitter);
        if (!ValidateEffectPlayback(effectRecord, baselineRecord, targetEffect, baselineEffect, "state_child_effects", check))
        {
            return;
        }

        check.Details.Add("state_child_effects_ok=" + group.Name + ":" + targetEffect.ValueName);
    }

    private static void VerifySwitchChildEffects(AudioForgeDatabase database, AudioForgeRuntime runtime, AudioForgeEmitterHandle emitter, AudioForgeValidationCheck check)
    {
        AudioForgeSwitchGroupConfig group = FindSwitchEffectGroup(database);
        if (group == null)
        {
            check.Details.Add("switch_child_effects_skipped");
            return;
        }

        AudioForgeGameSyncEffectConfig targetEffect = FindMeaningfulEffect(group.SwitchEffects);
        string baselineSwitch = ResolveAlternateValue(group.Switches, targetEffect != null ? targetEffect.ValueName : string.Empty, group.DefaultSwitch);
        AudioForgeEventConfig eventConfig = FindPlayableEvent(database);
        if (targetEffect == null || string.IsNullOrEmpty(baselineSwitch) || eventConfig == null)
        {
            check.Details.Add("switch_child_effects_incomplete");
            return;
        }

        AudioForgeGameSyncEffectConfig baselineEffect = FindEffect(group.SwitchEffects, baselineSwitch);
        runtime.SetSwitch(group.Name, baselineSwitch, emitter);
        AudioForgeDebugEventRecord baselineRecord = PlayAndGetLatestRecord(runtime, eventConfig, emitter);
        runtime.SetSwitch(group.Name, targetEffect.ValueName, emitter);
        AudioForgeDebugEventRecord effectRecord = PlayAndGetLatestRecord(runtime, eventConfig, emitter);
        if (!ValidateEffectPlayback(effectRecord, baselineRecord, targetEffect, baselineEffect, "switch_child_effects", check))
        {
            return;
        }

        check.Details.Add("switch_child_effects_ok=" + group.Name + ":" + targetEffect.ValueName);
    }

    private static bool ValidateEffectPlayback(
        AudioForgeDebugEventRecord effectRecord,
        AudioForgeDebugEventRecord baselineRecord,
        AudioForgeGameSyncEffectConfig targetEffect,
        AudioForgeGameSyncEffectConfig baselineEffect,
        string detailPrefix,
        AudioForgeValidationCheck check)
    {
        if (effectRecord == null)
        {
            check.Passed = false;
            check.Details.Add(detailPrefix + "_missing_record");
            return false;
        }

        if (targetEffect.IsMuted)
        {
            if (!string.Equals(effectRecord.Result, "rejected", StringComparison.Ordinal))
            {
                check.Passed = false;
                check.Details.Add(detailPrefix + "_mute_expected_rejected=" + effectRecord.Result);
                return false;
            }
            return true;
        }

        if (baselineRecord == null || !string.Equals(effectRecord.Result, "played", StringComparison.Ordinal) || !string.Equals(baselineRecord.Result, "played", StringComparison.Ordinal))
        {
            check.Passed = false;
            check.Details.Add(detailPrefix + "_playback_failed");
            return false;
        }

        float baselineVolumeDb = baselineEffect != null ? baselineEffect.VolumeDb : 0f;
        int baselinePitchCents = baselineEffect != null ? baselineEffect.PitchCents : 0;
        float expectedVolumeDelta = targetEffect.VolumeDb - baselineVolumeDb;
        int expectedPitchDelta = targetEffect.PitchCents - baselinePitchCents;
        float actualVolumeDelta = effectRecord.VolumeDb - baselineRecord.VolumeDb;
        int actualPitchDelta = effectRecord.PitchCents - baselineRecord.PitchCents;
        if (Mathf.Abs(actualVolumeDelta - expectedVolumeDelta) > 0.05f)
        {
            check.Passed = false;
            check.Details.Add(detailPrefix + "_volume_mismatch=" + actualVolumeDelta.ToString("F2") + ":expected=" + expectedVolumeDelta.ToString("F2"));
            return false;
        }
        if (actualPitchDelta != expectedPitchDelta)
        {
            check.Passed = false;
            check.Details.Add(detailPrefix + "_pitch_mismatch=" + actualPitchDelta + ":expected=" + expectedPitchDelta);
            return false;
        }

        return true;
    }

    private static AudioForgeDebugEventRecord PlayAndGetLatestRecord(AudioForgeRuntime runtime, AudioForgeEventConfig eventConfig, AudioForgeEmitterHandle emitter)
    {
        if (runtime == null || eventConfig == null)
        {
            return null;
        }

        RunEnumerator(runtime.PlayEvent(eventConfig.EventId, emitter));
        List<AudioForgeDebugEventRecord> records = runtime.GetRecentDebugEventRecords();
        for (int index = 0; index < records.Count; index += 1)
        {
            AudioForgeDebugEventRecord record = records[index];
            if (record != null && string.Equals(record.EventId, eventConfig.EventId, StringComparison.Ordinal))
            {
                return record;
            }
        }

        return null;
    }

    private static AudioForgeStateGroupConfig FindStateEffectGroup(AudioForgeDatabase database)
    {
        for (int index = 0; index < database.StateGroups.Count; index += 1)
        {
            AudioForgeStateGroupConfig group = database.StateGroups[index];
            if (group != null && group.StateEffects.Count > 0)
            {
                return group;
            }
        }

        return null;
    }

    private static AudioForgeSwitchGroupConfig FindSwitchEffectGroup(AudioForgeDatabase database)
    {
        for (int index = 0; index < database.SwitchGroups.Count; index += 1)
        {
            AudioForgeSwitchGroupConfig group = database.SwitchGroups[index];
            if (group != null && group.SwitchEffects.Count > 0)
            {
                return group;
            }
        }

        return null;
    }

    private static AudioForgeGameSyncEffectConfig FindMeaningfulEffect(List<AudioForgeGameSyncEffectConfig> effects)
    {
        if (effects == null)
        {
            return null;
        }

        for (int index = 0; index < effects.Count; index += 1)
        {
            AudioForgeGameSyncEffectConfig effect = effects[index];
            if (effect != null && !string.IsNullOrEmpty(effect.ValueName) && (effect.IsMuted || Math.Abs(effect.VolumeDb) > 0.01f || effect.PitchCents != 0))
            {
                return effect;
            }
        }

        return effects.Count > 0 ? effects[0] : null;
    }

    private static AudioForgeGameSyncEffectConfig FindEffect(List<AudioForgeGameSyncEffectConfig> effects, string valueName)
    {
        if (effects == null || string.IsNullOrEmpty(valueName))
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

    private static string ResolveAlternateValue(List<string> values, string targetValue, string preferredValue)
    {
        if (!string.IsNullOrEmpty(preferredValue) && !string.Equals(preferredValue, targetValue, StringComparison.Ordinal))
        {
            return preferredValue;
        }

        if (values == null)
        {
            return string.Empty;
        }

        for (int index = 0; index < values.Count; index += 1)
        {
            string value = values[index];
            if (!string.IsNullOrEmpty(value) && !string.Equals(value, targetValue, StringComparison.Ordinal))
            {
                return value;
            }
        }

        return string.Empty;
    }

    private static AudioForgeEventConfig FindPlayableEvent(AudioForgeDatabase database)
    {
        for (int index = 0; index < database.Events.Count; index += 1)
        {
            AudioForgeEventConfig eventConfig = database.Events[index];
            if (eventConfig != null && eventConfig.Clips.Count > 0)
            {
                return eventConfig;
            }
        }

        return null;
    }

    private static AudioForgeEventConfig FindPlayableEventWithoutStateOverride(AudioForgeDatabase database, string stateGroupName)
    {
        for (int index = 0; index < database.Events.Count; index += 1)
        {
            AudioForgeEventConfig eventConfig = database.Events[index];
            if (eventConfig == null || eventConfig.Clips.Count == 0)
            {
                continue;
            }

            bool usesOverride = false;
            for (int overrideIndex = 0; overrideIndex < eventConfig.StateOverrides.Count; overrideIndex += 1)
            {
                AudioForgeStateOverrideConfig item = eventConfig.StateOverrides[overrideIndex];
                if (item != null && string.Equals(item.GroupName, stateGroupName, StringComparison.Ordinal))
                {
                    usesOverride = true;
                    break;
                }
            }

            if (!usesOverride)
            {
                return eventConfig;
            }
        }

        return FindPlayableEvent(database);
    }

    private static AudioForgeEventConfig FindSwitchVariantEvent(AudioForgeDatabase database)
    {
        for (int index = 0; index < database.Events.Count; index += 1)
        {
            AudioForgeEventConfig eventConfig = database.Events[index];
            if (eventConfig != null && eventConfig.SwitchVariants.Count > 0)
            {
                return eventConfig;
            }
        }

        return null;
    }

    private static void RunEnumerator(IEnumerator routine)
    {
        if (routine == null)
        {
            return;
        }

        while (routine.MoveNext())
        {
        }
    }

    private static int CountMissingScriptsRecursive(GameObject gameObject, List<string> details)
    {
        int count = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(gameObject);
        if (count > 0)
        {
            details.Add("missing_on_object=" + GetHierarchyPath(gameObject) + ":" + count);
        }

        Transform transform = gameObject.transform;
        for (int index = 0; index < transform.childCount; index += 1)
        {
            count += CountMissingScriptsRecursive(transform.GetChild(index).gameObject, details);
        }

        return count;
    }

    private static void ValidateBootstrapBindings(AudioForgeBootstrap[] bootstraps, Dictionary<string, bool> eventIds, AudioForgeValidationCheck check)
    {
        for (int index = 0; index < bootstraps.Length; index += 1)
        {
            AudioForgeBootstrap bootstrap = bootstraps[index];
            if (bootstrap == null)
            {
                continue;
            }

            string eventId = bootstrap.EventId;
            if (string.IsNullOrEmpty(eventId))
            {
                check.Passed = false;
                check.Details.Add("bootstrap_event_empty=" + GetHierarchyPath(bootstrap.gameObject));
            }
            else if (eventIds.Count > 0 && !eventIds.ContainsKey(eventId))
            {
                check.Passed = false;
                check.Details.Add("bootstrap_event_missing=" + GetHierarchyPath(bootstrap.gameObject) + ":" + eventId);
            }
        }
    }

    private static void ValidateEventPlayerBindings(AudioForgeEventPlayer[] eventPlayers, Dictionary<string, bool> eventIds, AudioForgeValidationCheck check)
    {
        for (int index = 0; index < eventPlayers.Length; index += 1)
        {
            AudioForgeEventPlayer eventPlayer = eventPlayers[index];
            if (eventPlayer == null)
            {
                continue;
            }

            string eventId = eventPlayer.EventId;
            if (string.IsNullOrEmpty(eventId))
            {
                check.Passed = false;
                check.Details.Add("event_player_event_empty=" + GetHierarchyPath(eventPlayer.gameObject));
            }
            else if (eventIds.Count > 0 && !eventIds.ContainsKey(eventId))
            {
                check.Passed = false;
                check.Details.Add("event_player_event_missing=" + GetHierarchyPath(eventPlayer.gameObject) + ":" + eventId);
            }
        }
    }

    private static string GetHierarchyPath(GameObject gameObject)
    {
        StringBuilder builder = new StringBuilder(gameObject.name);
        Transform current = gameObject.transform.parent;
        while (current != null)
        {
            builder.Insert(0, current.name + "/");
            current = current.parent;
        }
        return builder.ToString();
    }

    private static void WriteReportFiles(AudioForgeValidationReport report)
    {
        string reportRoot = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "AudioForgeReports");
        Directory.CreateDirectory(reportRoot);

        string timestamp = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss");
        string jsonPath = Path.Combine(reportRoot, "unity_validation_report_" + timestamp + ".json");
        string markdownPath = Path.Combine(reportRoot, "unity_validation_report_" + timestamp + ".md");

        report.JsonReportPath = jsonPath;
        report.MarkdownReportPath = markdownPath;

        File.WriteAllText(jsonPath, JsonUtility.ToJson(report, true), Encoding.UTF8);
        File.WriteAllText(markdownPath, BuildMarkdown(report), Encoding.UTF8);
        AssetDatabase.Refresh();
    }

    private static string BuildMarkdown(AudioForgeValidationReport report)
    {
        StringBuilder builder = new StringBuilder();
        builder.AppendLine("# AudioForge Unity Validation Report");
        builder.AppendLine();
        builder.AppendLine("- Generated At: " + report.GeneratedAtUtc);
        builder.AppendLine("- Overall: " + (report.Passed ? "PASS" : "FAIL"));
        builder.AppendLine("- Scene: " + report.ScenePath);
        builder.AppendLine("- Project Root: " + report.ProjectRoot);
        builder.AppendLine();
        builder.AppendLine("## Checks");
        builder.AppendLine();

        for (int index = 0; index < report.Checks.Count; index += 1)
        {
            AudioForgeValidationCheck check = report.Checks[index];
            builder.AppendLine("### " + check.Name + " - " + (check.Passed ? "PASS" : "FAIL"));
            builder.AppendLine();
            for (int detailIndex = 0; detailIndex < check.Details.Count; detailIndex += 1)
            {
                builder.AppendLine("- " + check.Details[detailIndex]);
            }
            builder.AppendLine();
        }

        return builder.ToString();
    }

    private static void LogSummary(AudioForgeValidationReport report)
    {
        Debug.Log(
            "AudioForge validation completed: "
            + (report.Passed ? "PASS" : "FAIL")
            + " | json=" + report.JsonReportPath
            + " | markdown=" + report.MarkdownReportPath
        );

        if (!report.Passed)
        {
            Debug.LogWarning("AudioForge validation found failures. Check generated reports for details.");
        }
    }
}

[Serializable]
public sealed class AudioForgeValidationReport
{
    public string GeneratedAtUtc;
    public string ProjectRoot;
    public string ScenePath;
    public bool Passed;
    public string JsonReportPath;
    public string MarkdownReportPath;
    public List<AudioForgeValidationCheck> Checks = new List<AudioForgeValidationCheck>();
}

[Serializable]
public sealed class AudioForgeValidationCheck
{
    public string Name;
    public bool Passed;
    public List<string> Details = new List<string>();
}