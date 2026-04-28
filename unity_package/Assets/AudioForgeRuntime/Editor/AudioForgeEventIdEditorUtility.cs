using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

internal static class AudioForgeEventIdEditorUtility
{
    private const string RefreshMenuPath = "AudioForge/Tools/Refresh AudioEventID From StreamingAssets";
    private const string AudioDataRelativePath = "AudioForge/AudioData.json";
    private const string EventIdEnumScriptPath = "Assets/AudioForgeRuntime/Scripts/AudioEventID.cs";

    [MenuItem(RefreshMenuPath)]
    public static void RefreshAudioEventIdFromStreamingAssets()
    {
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath);
        if (!File.Exists(audioDataPath))
        {
            EditorUtility.DisplayDialog("AudioForge", "没有找到 StreamingAssets/AudioForge/AudioData.json。", "确定");
            return;
        }

        string json = File.ReadAllText(audioDataPath);
        AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
        List<string> eventIds = ExtractEventIds(database);
        if (eventIds.Count == 0)
        {
            EditorUtility.DisplayDialog("AudioForge", "AudioData.json 中没有可写入的事件 ID。", "确定");
            return;
        }

        string scriptPath = Path.Combine(Directory.GetParent(Application.dataPath).FullName, EventIdEnumScriptPath);
        File.WriteAllText(scriptPath, BuildEnumSource(eventIds), new UTF8Encoding(false));
        AssetDatabase.Refresh();
        Debug.Log("AudioForge refreshed AudioEventID.cs from StreamingAssets/AudioData.json");
    }

    public static List<string> GetAvailableEventIds()
    {
        List<string> eventIds = GetEventIdsFromStreamingAssets();
        if (eventIds.Count > 0)
        {
            return eventIds;
        }

        eventIds = GetEventIdsFromEnum();
        eventIds.Sort(StringComparer.OrdinalIgnoreCase);
        return eventIds;
    }

    public static bool HasEventId(string eventId)
    {
        if (string.IsNullOrWhiteSpace(eventId))
        {
            return false;
        }

        List<string> eventIds = GetAvailableEventIds();
        return eventIds.Contains(eventId);
    }

    public static List<AudioForgeEditorEventSummary> GetAvailableEventSummaries()
    {
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath);
        List<AudioForgeEditorEventSummary> summaries = new List<AudioForgeEditorEventSummary>();
        if (!File.Exists(audioDataPath))
        {
            return summaries;
        }

        try
        {
            string json = File.ReadAllText(audioDataPath);
            AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
            if (database == null || database.Events == null)
            {
                return summaries;
            }

            for (int index = 0; index < database.Events.Count; index += 1)
            {
                AudioForgeEventConfig eventConfig = database.Events[index];
                if (eventConfig == null || string.IsNullOrWhiteSpace(eventConfig.EventId))
                {
                    continue;
                }

                AudioForgeEditorEventSummary summary = new AudioForgeEditorEventSummary();
                summary.EventId = eventConfig.EventId.Trim();
                summary.BusName = string.IsNullOrWhiteSpace(eventConfig.Bus) ? "SFX" : eventConfig.Bus.Trim();
                summary.VolumeDb = eventConfig.VolumeDb;
                summary.PlayMode = string.IsNullOrWhiteSpace(eventConfig.PlayMode) ? "Random" : eventConfig.PlayMode.Trim();
                summary.ClipCount = eventConfig.Clips != null ? eventConfig.Clips.Count : 0;
                summaries.Add(summary);
            }

            summaries.Sort(delegate(AudioForgeEditorEventSummary left, AudioForgeEditorEventSummary right)
            {
                return string.Compare(left.EventId, right.EventId, StringComparison.OrdinalIgnoreCase);
            });
            return summaries;
        }
        catch (Exception exception)
        {
            Debug.LogWarning("AudioForge could not parse AudioData.json for event summaries: " + exception.Message);
            return summaries;
        }
    }

    public static AudioForgeEditorEventSummary GetEventSummary(string eventId)
    {
        if (string.IsNullOrWhiteSpace(eventId))
        {
            return null;
        }

        List<AudioForgeEditorEventSummary> summaries = GetAvailableEventSummaries();
        for (int index = 0; index < summaries.Count; index += 1)
        {
            AudioForgeEditorEventSummary summary = summaries[index];
            if (summary != null && string.Equals(summary.EventId, eventId.Trim(), StringComparison.Ordinal))
            {
                return summary;
            }
        }

        return null;
    }

    public static bool HasStreamingAudioData()
    {
        return File.Exists(Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath));
    }

    public static AudioForgeEditorAudioDataSummary GetAudioDataSummary()
    {
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath);
        AudioForgeEditorAudioDataSummary summary = new AudioForgeEditorAudioDataSummary();
        summary.AudioDataPath = audioDataPath;

        if (!File.Exists(audioDataPath))
        {
            return summary;
        }

        try
        {
            string json = File.ReadAllText(audioDataPath);
            AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
            summary.Exists = true;
            summary.ProjectName = database != null ? database.ProjectName : string.Empty;
            summary.RuntimeAudioFormat = database != null ? database.RuntimeAudioFormat : string.Empty;
            summary.EventCount = database != null && database.Events != null ? database.Events.Count : 0;
            summary.BusCount = database != null && database.BusConfigs != null ? database.BusConfigs.Count : 0;
            return summary;
        }
        catch (Exception exception)
        {
            summary.ParseError = exception.Message;
            return summary;
        }
    }

    public static List<AudioForgeEditorBusSummary> GetAvailableBusSummaries()
    {
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath);
        List<AudioForgeEditorBusSummary> summaries = new List<AudioForgeEditorBusSummary>();
        if (!File.Exists(audioDataPath))
        {
            return summaries;
        }

        try
        {
            string json = File.ReadAllText(audioDataPath);
            AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
            if (database == null)
            {
                return summaries;
            }

            if (database.BusConfigs != null)
            {
                for (int index = 0; index < database.BusConfigs.Count; index += 1)
                {
                    AudioForgeBusConfig busConfig = database.BusConfigs[index];
                    if (busConfig == null || string.IsNullOrWhiteSpace(busConfig.Name))
                    {
                        continue;
                    }

                    AudioForgeEditorBusSummary summary = new AudioForgeEditorBusSummary();
                    summary.BusName = busConfig.Name.Trim();
                    summary.ParentBusName = string.IsNullOrWhiteSpace(busConfig.ParentBus) ? "Master" : busConfig.ParentBus.Trim();
                    summary.VolumeDb = busConfig.VolumeDb;
                    summary.LinearVolume = Mathf.Max(0f, Mathf.Pow(10f, busConfig.VolumeDb / 20f));
                    summary.IsMuted = busConfig.IsMuted;
                    summaries.Add(summary);
                }
            }

            if (database.Buses != null)
            {
                for (int index = 0; index < database.Buses.Count; index += 1)
                {
                    string busName = database.Buses[index];
                    if (string.IsNullOrWhiteSpace(busName))
                    {
                        continue;
                    }

                    string normalizedName = busName.Trim();
                    bool exists = false;
                    for (int summaryIndex = 0; summaryIndex < summaries.Count; summaryIndex += 1)
                    {
                        if (string.Equals(summaries[summaryIndex].BusName, normalizedName, StringComparison.OrdinalIgnoreCase))
                        {
                            exists = true;
                            break;
                        }
                    }

                    if (!exists)
                    {
                        AudioForgeEditorBusSummary summary = new AudioForgeEditorBusSummary();
                        summary.BusName = normalizedName;
                        summary.ParentBusName = "Master";
                        summary.VolumeDb = 0f;
                        summary.LinearVolume = 1f;
                        summaries.Add(summary);
                    }
                }
            }

            summaries.Sort(delegate(AudioForgeEditorBusSummary left, AudioForgeEditorBusSummary right)
            {
                return string.Compare(left.BusName, right.BusName, StringComparison.OrdinalIgnoreCase);
            });
            return summaries;
        }
        catch (Exception exception)
        {
            Debug.LogWarning("AudioForge could not parse AudioData.json for bus summaries: " + exception.Message);
            return summaries;
        }
    }

    private static List<string> GetEventIdsFromStreamingAssets()
    {
        string audioDataPath = Path.Combine(Application.streamingAssetsPath, AudioDataRelativePath);
        if (!File.Exists(audioDataPath))
        {
            return new List<string>();
        }

        try
        {
            string json = File.ReadAllText(audioDataPath);
            AudioForgeDatabase database = AudioForgeJsonAdapter.Parse(json);
            return ExtractEventIds(database);
        }
        catch (Exception exception)
        {
            Debug.LogWarning("AudioForge could not parse AudioData.json for EventId search: " + exception.Message);
            return new List<string>();
        }
    }

    private static List<string> GetEventIdsFromEnum()
    {
        string[] enumNames = Enum.GetNames(typeof(AudioEventID));
        return new List<string>(enumNames ?? Array.Empty<string>());
    }

    private static List<string> ExtractEventIds(AudioForgeDatabase database)
    {
        List<string> eventIds = new List<string>();
        if (database == null || database.Events == null)
        {
            return eventIds;
        }

        for (int index = 0; index < database.Events.Count; index += 1)
        {
            AudioForgeEventConfig eventConfig = database.Events[index];
            if (eventConfig == null || string.IsNullOrWhiteSpace(eventConfig.EventId))
            {
                continue;
            }

            string eventId = eventConfig.EventId.Trim();
            if (!eventIds.Contains(eventId))
            {
                eventIds.Add(eventId);
            }
        }

        eventIds.Sort(StringComparer.OrdinalIgnoreCase);
        return eventIds;
    }

    private static string BuildEnumSource(List<string> eventIds)
    {
        StringBuilder builder = new StringBuilder();
        builder.AppendLine("public enum AudioEventID");
        builder.AppendLine("{");
        for (int index = 0; index < eventIds.Count; index += 1)
        {
            string identifier = SanitizeIdentifier(eventIds[index]);
            builder.Append("    ");
            builder.Append(identifier);
            if (index < eventIds.Count - 1)
            {
                builder.Append(',');
            }
            builder.AppendLine();
        }
        builder.AppendLine("}");
        return builder.ToString();
    }

    private static string SanitizeIdentifier(string rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
        {
            return "UnnamedEvent";
        }

        StringBuilder builder = new StringBuilder(rawValue.Length);
        for (int index = 0; index < rawValue.Length; index += 1)
        {
            char character = rawValue[index];
            if (char.IsLetterOrDigit(character) || character == '_')
            {
                builder.Append(character);
            }
            else
            {
                builder.Append('_');
            }
        }

        if (builder.Length == 0)
        {
            builder.Append("UnnamedEvent");
        }

        if (!char.IsLetter(builder[0]) && builder[0] != '_')
        {
            builder.Insert(0, '_');
        }

        return builder.ToString();
    }
}

internal sealed class AudioForgeEditorAudioDataSummary
{
    public bool Exists;
    public string AudioDataPath;
    public string ProjectName;
    public string RuntimeAudioFormat;
    public int EventCount;
    public int BusCount;
    public string ParseError;
}

internal sealed class AudioForgeEditorBusSummary
{
    public string BusName;
    public string ParentBusName;
    public float VolumeDb;
    public float LinearVolume = 1f;
    public bool IsMuted;
}

internal sealed class AudioForgeEditorEventSummary
{
    public string EventId;
    public string BusName;
    public float VolumeDb;
    public string PlayMode;
    public int ClipCount;
}
