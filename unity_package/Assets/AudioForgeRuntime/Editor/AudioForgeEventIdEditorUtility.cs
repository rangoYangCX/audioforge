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
