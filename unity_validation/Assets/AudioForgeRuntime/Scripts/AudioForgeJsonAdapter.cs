using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 将 AudioData.json 反序列化为 Unity 侧可直接消费的数据结构。
/// 这里刻意保持“宽读取、窄使用”：只读取参考运行时当前需要的字段。
/// </summary>
public static class AudioForgeJsonAdapter
{
    public static AudioForgeDatabase Parse(string json)
    {
        var root = MiniJson.Deserialize(json) as Dictionary<string, object>;
        if (root == null)
        {
            throw new InvalidOperationException("AudioData.json root is invalid.");
        }

        var database = new AudioForgeDatabase
        {
            SchemaVersion = Convert.ToInt32(root["SchemaVersion"]),
            ProjectName = root.TryGetValue("ProjectName", out var projectName) ? projectName?.ToString() : string.Empty,
            RuntimeAudioFormat = root.TryGetValue("RuntimeAudioFormat", out var runtimeFormat) ? runtimeFormat?.ToString() ?? "ogg" : "ogg",
        };

        foreach (Dictionary<string, object> parameterPayload in EnumerateObjectList(root, "GameParameters"))
        {
            database.GameParameters.Add(
                new AudioForgeGameParameterConfig
                {
                    Name = ReadString(parameterPayload, "Name"),
                    DefaultValue = ReadFloat(parameterPayload, "DefaultValue"),
                    MinValue = ReadFloat(parameterPayload, "MinValue"),
                    MaxValue = ReadFloat(parameterPayload, "MaxValue"),
                    Description = ReadString(parameterPayload, "Description"),
                }
            );
        }

        foreach (Dictionary<string, object> stateGroupPayload in EnumerateObjectList(root, "StateGroups"))
        {
            var group = new AudioForgeStateGroupConfig
            {
                Name = ReadString(stateGroupPayload, "Name"),
                DefaultState = ReadString(stateGroupPayload, "DefaultState"),
            };
            group.States.AddRange(ReadStringList(stateGroupPayload, "States"));
            group.StateEffects.AddRange(ReadGameSyncEffects(stateGroupPayload, "StateEffects", "StateName"));
            database.StateGroups.Add(group);
        }

        foreach (Dictionary<string, object> switchGroupPayload in EnumerateObjectList(root, "SwitchGroups"))
        {
            var group = new AudioForgeSwitchGroupConfig
            {
                Name = ReadString(switchGroupPayload, "Name"),
                DefaultSwitch = ReadString(switchGroupPayload, "DefaultSwitch"),
                UseGameParameter = ReadBool(switchGroupPayload, "UseGameParameter"),
                MappedGameParameter = ReadString(switchGroupPayload, "MappedGameParameter"),
            };
            group.Switches.AddRange(ReadStringList(switchGroupPayload, "Switches"));
            foreach (Dictionary<string, object> thresholdPayload in EnumerateObjectList(switchGroupPayload, "Thresholds"))
            {
                group.Thresholds.Add(
                    new AudioForgeSwitchThresholdConfig
                    {
                        SwitchName = ReadString(thresholdPayload, "SwitchName"),
                        MinValue = ReadFloat(thresholdPayload, "MinValue"),
                        MaxValue = ReadFloat(thresholdPayload, "MaxValue"),
                    }
                );
            }
            group.SwitchEffects.AddRange(ReadGameSyncEffects(switchGroupPayload, "SwitchEffects", "SwitchName"));
            database.SwitchGroups.Add(group);
        }

        var audioObjectMap = new Dictionary<string, AudioForgeAudioObjectConfig>();
        var audioObjectsObject = root.ContainsKey("AudioObjects") ? root["AudioObjects"] as Dictionary<string, object> : null;
        if (audioObjectsObject != null)
        {
            foreach (var pair in audioObjectsObject)
            {
                var audioPayload = pair.Value as Dictionary<string, object>;
                if (audioPayload == null)
                {
                    continue;
                }

                var audioConfig = new AudioForgeAudioObjectConfig
                {
                    AudioId = pair.Key,
                    DisplayName = ReadString(audioPayload, "DisplayName"),
                    Bus = ReadString(audioPayload, "Bus"),
                    PlayMode = ReadString(audioPayload, "PlayMode"),
                    AvoidImmediateRepeat = ReadBool(audioPayload, "AvoidImmediateRepeat"),
                    VolumeDb = ReadFloat(audioPayload, "VolumeDb"),
                    VolumeRandMinDb = ReadFloatArrayValue(audioPayload, "VolumeRandDb", 0),
                    VolumeRandMaxDb = ReadFloatArrayValue(audioPayload, "VolumeRandDb", 1),
                    PitchCents = ReadInt(audioPayload, "PitchCents"),
                    PitchRandMinCents = ReadIntArrayValue(audioPayload, "PitchRandCents", 0),
                    PitchRandMaxCents = ReadIntArrayValue(audioPayload, "PitchRandCents", 1),
                    LoadPolicy = ReadString(audioPayload, "LoadPolicy"),
                    ComboPitchStepCents = ReadInt(audioPayload, "ComboPitchStepCents"),
                    ComboResetSeconds = ReadFloat(audioPayload, "ComboResetSeconds"),
                    ComboMaxStep = ReadInt(audioPayload, "ComboMaxStep"),
                    RtpcBindings = ReadRtpcBindings(audioPayload, "RtpcBindings"),
                    StateOverrides = ReadStateOverrides(audioPayload, "StateOverrides"),
                    SwitchVariants = ReadSwitchVariants(audioPayload, "SwitchVariants"),
                };
                audioConfig.DefaultClipIds.AddRange(ReadStringList(audioPayload, "DefaultClipIds"));

                var clips = audioPayload.ContainsKey("Clips") ? audioPayload["Clips"] as IList : null;
                if (clips != null)
                {
                    foreach (var clipObject in clips)
                    {
                        var clipPayload = clipObject as Dictionary<string, object>;
                        if (clipPayload == null)
                        {
                            continue;
                        }

                        audioConfig.Clips.Add(new AudioForgeClipConfig
                        {
                            ClipId = ReadString(clipPayload, "ClipId"),
                            AssetKey = ReadString(clipPayload, "AssetKey"),
                            Weight = ReadInt(clipPayload, "Weight"),
                            TrimStartMs = ReadInt(clipPayload, "TrimStartMs"),
                            TrimEndMs = ReadInt(clipPayload, "TrimEndMs"),
                            FadeInMs = ReadInt(clipPayload, "FadeInMs"),
                            FadeOutMs = ReadInt(clipPayload, "FadeOutMs"),
                            LoopStartMs = ReadInt(clipPayload, "LoopStartMs"),
                            LoopEndMs = ReadInt(clipPayload, "LoopEndMs"),
                        });
                    }
                }

                database.AudioObjects.Add(audioConfig);
                audioObjectMap[audioConfig.AudioId] = audioConfig;
            }
        }

        IList busConfigsObject = root.ContainsKey("BusConfigs") ? root["BusConfigs"] as IList : null;
        if (busConfigsObject != null)
        {
            foreach (object busConfigObject in busConfigsObject)
            {
                var busConfigPayload = busConfigObject as Dictionary<string, object>;
                if (busConfigPayload == null)
                {
                    continue;
                }

                string busName = ReadString(busConfigPayload, "Name");
                if (string.IsNullOrEmpty(busName))
                {
                    continue;
                }

                database.Buses.Add(busName);
                database.BusConfigs.Add(
                    new AudioForgeBusConfig
                    {
                        Name = busName,
                        ParentBus = ReadString(busConfigPayload, "ParentBus"),
                        VolumeDb = ReadFloat(busConfigPayload, "VolumeDb"),
                        IsMuted = ReadBool(busConfigPayload, "IsMuted"),
                        RtpcBindings = ReadRtpcBindings(busConfigPayload, "RtpcBindings"),
                        StateOverrides = ReadStateOverrides(busConfigPayload, "StateOverrides"),
                    }
                );
            }
        }

        IList busesObject = root.ContainsKey("Buses") ? root["Buses"] as IList : null;
        if (database.Buses.Count == 0 && busesObject != null)
        {
            foreach (object busObject in busesObject)
            {
                if (busObject == null)
                {
                    continue;
                }

                string busName = busObject.ToString();
                if (!string.IsNullOrEmpty(busName))
                {
                    database.Buses.Add(busName);
                    database.BusConfigs.Add(new AudioForgeBusConfig { Name = busName, ParentBus = "Master", VolumeDb = 0f, IsMuted = false });
                }
            }
        }

        var eventsObject = root["Events"] as Dictionary<string, object>;
        if (eventsObject == null)
        {
            return database;
        }

        foreach (var pair in eventsObject)
        {
            var eventPayload = pair.Value as Dictionary<string, object>;
            if (eventPayload == null)
            {
                continue;
            }

            var eventConfig = new AudioForgeEventConfig
            {
                EventId = pair.Key,
                MaxInstances = ReadInt(eventPayload, "MaxInstances"),
                CooldownSeconds = ReadFloat(eventPayload, "CooldownSeconds"),
                StealPolicy = ReadString(eventPayload, "StealPolicy"),
                AudioId = ReadString(eventPayload, "AudioId"),
            };

            if (string.IsNullOrEmpty(eventConfig.AudioId) || !audioObjectMap.TryGetValue(eventConfig.AudioId, out var audioConfig))
            {
                throw new InvalidOperationException("Event is missing a valid AudioId reference: " + pair.Key);
            }

            eventConfig.Audio = audioConfig;

            database.Events.Add(eventConfig);
        }

        return database;
    }

    private static List<AudioForgeRtpcBindingConfig> ReadRtpcBindings(Dictionary<string, object> payload, string key)
    {
        var result = new List<AudioForgeRtpcBindingConfig>();
        foreach (Dictionary<string, object> bindingPayload in EnumerateObjectList(payload, key))
        {
            var binding = new AudioForgeRtpcBindingConfig
            {
                ParameterName = ReadString(bindingPayload, "ParameterName"),
                Target = ReadString(bindingPayload, "Target"),
                Scope = ReadString(bindingPayload, "Scope"),
            };
            foreach (Dictionary<string, object> pointPayload in EnumerateObjectList(bindingPayload, "CurvePoints"))
            {
                binding.CurvePoints.Add(
                    new AudioForgeCurvePointConfig
                    {
                        InputValue = ReadFloat(pointPayload, "InputValue"),
                        OutputValue = ReadFloat(pointPayload, "OutputValue"),
                        Interpolation = ReadString(pointPayload, "Interpolation"),
                    }
                );
            }
            result.Add(binding);
        }
        return result;
    }

    private static List<AudioForgeStateOverrideConfig> ReadStateOverrides(Dictionary<string, object> payload, string key)
    {
        var result = new List<AudioForgeStateOverrideConfig>();
        foreach (Dictionary<string, object> overridePayload in EnumerateObjectList(payload, key))
        {
            result.Add(
                new AudioForgeStateOverrideConfig
                {
                    GroupName = ReadString(overridePayload, "GroupName"),
                    StateName = ReadString(overridePayload, "StateName"),
                    VolumeDb = ReadFloat(overridePayload, "VolumeDb"),
                    PitchCents = ReadInt(overridePayload, "PitchCents"),
                    IsMuted = ReadBool(overridePayload, "IsMuted"),
                }
            );
        }
        return result;
    }

    private static List<AudioForgeSwitchVariantConfig> ReadSwitchVariants(Dictionary<string, object> payload, string key)
    {
        var result = new List<AudioForgeSwitchVariantConfig>();
        foreach (Dictionary<string, object> variantPayload in EnumerateObjectList(payload, key))
        {
            var variant = new AudioForgeSwitchVariantConfig
            {
                GroupName = ReadString(variantPayload, "GroupName"),
                SwitchName = ReadString(variantPayload, "SwitchName"),
            };
            variant.ClipIds.AddRange(ReadStringList(variantPayload, "ClipIds"));
            result.Add(variant);
        }
        return result;
    }

    private static List<AudioForgeGameSyncEffectConfig> ReadGameSyncEffects(Dictionary<string, object> payload, string key, string nameKey)
    {
        var result = new List<AudioForgeGameSyncEffectConfig>();
        foreach (Dictionary<string, object> effectPayload in EnumerateObjectList(payload, key))
        {
            result.Add(
                new AudioForgeGameSyncEffectConfig
                {
                    ValueName = ReadString(effectPayload, nameKey),
                    VolumeDb = ReadFloat(effectPayload, "VolumeDb"),
                    PitchCents = ReadInt(effectPayload, "PitchCents"),
                    IsMuted = ReadBool(effectPayload, "IsMuted"),
                    Notes = ReadString(effectPayload, "Notes"),
                }
            );
        }
        return result;
    }

    private static IEnumerable<Dictionary<string, object>> EnumerateObjectList(Dictionary<string, object> payload, string key)
    {
        if (!payload.TryGetValue(key, out var value))
        {
            yield break;
        }

        IList list = value as IList;
        if (list == null)
        {
            yield break;
        }

        foreach (object item in list)
        {
            Dictionary<string, object> objectPayload = item as Dictionary<string, object>;
            if (objectPayload != null)
            {
                yield return objectPayload;
            }
        }
    }

    private static List<string> ReadStringList(Dictionary<string, object> payload, string key)
    {
        var result = new List<string>();
        if (!payload.TryGetValue(key, out var value))
        {
            return result;
        }

        IList list = value as IList;
        if (list == null)
        {
            return result;
        }

        foreach (object item in list)
        {
            if (item == null)
            {
                continue;
            }
            result.Add(item.ToString());
        }
        return result;
    }

    private static string ReadString(Dictionary<string, object> payload, string key)
    {
        return payload.TryGetValue(key, out var value) ? value?.ToString() ?? string.Empty : string.Empty;
    }

    private static int ReadInt(Dictionary<string, object> payload, string key)
    {
        return payload.TryGetValue(key, out var value) ? Convert.ToInt32(value) : 0;
    }

    private static float ReadFloat(Dictionary<string, object> payload, string key)
    {
        return payload.TryGetValue(key, out var value) ? Convert.ToSingle(value) : 0f;
    }

    private static bool ReadBool(Dictionary<string, object> payload, string key)
    {
        return payload.TryGetValue(key, out var value) && Convert.ToBoolean(value);
    }

    private static float ReadFloatArrayValue(Dictionary<string, object> payload, string key, int index)
    {
        if (!payload.TryGetValue(key, out var value))
        {
            return 0f;
        }

        var list = value as IList;
        if (list == null || list.Count <= index)
        {
            return 0f;
        }

        return Convert.ToSingle(list[index]);
    }

    private static int ReadIntArrayValue(Dictionary<string, object> payload, string key, int index)
    {
        if (!payload.TryGetValue(key, out var value))
        {
            return 0;
        }

        var list = value as IList;
        if (list == null || list.Count <= index)
        {
            return 0;
        }

        return Convert.ToInt32(list[index]);
    }
}