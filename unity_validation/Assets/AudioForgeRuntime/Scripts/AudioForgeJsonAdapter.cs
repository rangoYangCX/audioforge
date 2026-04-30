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
                Bus = ReadString(eventPayload, "Bus"),
                PlayMode = ReadString(eventPayload, "PlayMode"),
                AvoidImmediateRepeat = ReadBool(eventPayload, "AvoidImmediateRepeat"),
                VolumeDb = ReadFloat(eventPayload, "VolumeDb"),
                VolumeRandMinDb = ReadFloatArrayValue(eventPayload, "VolumeRandDb", 0),
                VolumeRandMaxDb = ReadFloatArrayValue(eventPayload, "VolumeRandDb", 1),
                PitchCents = ReadInt(eventPayload, "PitchCents"),
                PitchRandMinCents = ReadIntArrayValue(eventPayload, "PitchRandCents", 0),
                PitchRandMaxCents = ReadIntArrayValue(eventPayload, "PitchRandCents", 1),
                MaxInstances = ReadInt(eventPayload, "MaxInstances"),
                CooldownSeconds = ReadFloat(eventPayload, "CooldownSeconds"),
                StealPolicy = ReadString(eventPayload, "StealPolicy"),
                LoadPolicy = ReadString(eventPayload, "LoadPolicy"),
                ComboPitchStepCents = ReadInt(eventPayload, "ComboPitchStepCents"),
                ComboResetSeconds = ReadFloat(eventPayload, "ComboResetSeconds"),
                ComboMaxStep = ReadInt(eventPayload, "ComboMaxStep"),
            };

            var clips = eventPayload["Clips"] as IList;
            if (clips != null)
            {
                foreach (var clipObject in clips)
                {
                    var clipPayload = clipObject as Dictionary<string, object>;
                    if (clipPayload == null)
                    {
                        continue;
                    }

                    eventConfig.Clips.Add(new AudioForgeClipConfig
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

            database.Events.Add(eventConfig);
        }

        return database;
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