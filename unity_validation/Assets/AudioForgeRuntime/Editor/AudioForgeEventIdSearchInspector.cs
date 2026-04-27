using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

internal static class AudioForgeEventIdSearchInspector
{
    private static readonly Dictionary<string, string> SearchQueries = new Dictionary<string, string>();
    private static readonly Dictionary<string, int> SelectedIndices = new Dictionary<string, int>();
    private static readonly Dictionary<string, string> LastClickedEventIds = new Dictionary<string, string>();
    private static readonly Dictionary<string, double> LastClickedTimes = new Dictionary<string, double>();
    private const double DoubleClickThresholdSeconds = 0.35d;

    public static void DrawEventIdField(SerializedObject serializedObject, SerializedProperty eventIdProperty, string stateKey)
    {
        EditorGUILayout.PropertyField(eventIdProperty, new GUIContent("Event Id"));

        List<string> eventIds = AudioForgeEventIdEditorUtility.GetAvailableEventIds();
        if (eventIds == null || eventIds.Count == 0)
        {
            EditorGUILayout.HelpBox("当前没有可搜索的事件 ID。请先导入 AudioData.json，或者执行 AudioForge/Tools/Refresh AudioEventID From StreamingAssets。", MessageType.Info);
            return;
        }

        string currentQuery;
        if (!SearchQueries.TryGetValue(stateKey, out currentQuery))
        {
            currentQuery = string.Empty;
        }

        EditorGUILayout.Space(2f);
        EditorGUILayout.LabelField("关联搜索", EditorStyles.boldLabel);
        string updatedQuery = EditorGUILayout.TextField("搜索事件", currentQuery);
        if (!string.Equals(updatedQuery, currentQuery, StringComparison.Ordinal))
        {
            SearchQueries[stateKey] = updatedQuery;
            SelectedIndices[stateKey] = 0;
        }

        List<string> filteredEventIds = FilterEventIds(eventIds, updatedQuery);
        if (filteredEventIds.Count == 0)
        {
            EditorGUILayout.HelpBox("没有匹配的事件 ID。可以继续手动输入，或者调整搜索关键字。", MessageType.Warning);
            return;
        }

        int selectedIndex;
        if (!SelectedIndices.TryGetValue(stateKey, out selectedIndex))
        {
            selectedIndex = 0;
        }
        selectedIndex = Mathf.Clamp(selectedIndex, 0, filteredEventIds.Count - 1);

        EditorGUILayout.LabelField("匹配结果", filteredEventIds.Count.ToString());
        selectedIndex = EditorGUILayout.Popup("候选事件", selectedIndex, filteredEventIds.ToArray());
        SelectedIndices[stateKey] = selectedIndex;

        EditorGUILayout.LabelField("快捷候选");
        int quickPickCount = Mathf.Min(8, filteredEventIds.Count);
        for (int index = 0; index < quickPickCount; index += 1)
        {
            string candidate = filteredEventIds[index];
            GUIStyle style = index == selectedIndex ? EditorStyles.miniButtonMid : EditorStyles.miniButton;
            if (GUILayout.Button(candidate, style))
            {
                SelectedIndices[stateKey] = index;
                if (WasDoubleClicked(stateKey, candidate))
                {
                    ApplySelectedEventId(serializedObject, eventIdProperty, candidate);
                }
                else
                {
                    RegisterClick(stateKey, candidate);
                }
            }
        }

        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("应用选中事件"))
        {
            ApplySelectedEventId(serializedObject, eventIdProperty, filteredEventIds[selectedIndex]);
        }
        if (GUILayout.Button("使用当前值过滤"))
        {
            string currentEventId = eventIdProperty.stringValue ?? string.Empty;
            SearchQueries[stateKey] = currentEventId;
            SelectedIndices[stateKey] = 0;
            GUI.FocusControl(null);
        }
        if (GUILayout.Button("刷新事件枚举"))
        {
            AudioForgeEventIdEditorUtility.RefreshAudioEventIdFromStreamingAssets();
            GUI.FocusControl(null);
        }
        EditorGUILayout.EndHorizontal();

        if (!AudioForgeEventIdEditorUtility.HasEventId(eventIdProperty.stringValue))
        {
            EditorGUILayout.HelpBox("当前 Event Id 不在导出的 AudioEventID 列表中，运行时可能无法关联到事件。", MessageType.Warning);
        }
    }

    private static void ApplySelectedEventId(SerializedObject serializedObject, SerializedProperty eventIdProperty, string eventId)
    {
        eventIdProperty.stringValue = eventId;
        serializedObject.ApplyModifiedProperties();
        GUI.FocusControl(null);
    }

    private static bool WasDoubleClicked(string stateKey, string candidate)
    {
        string lastClickedCandidate;
        double lastClickedTime;
        if (!LastClickedEventIds.TryGetValue(stateKey, out lastClickedCandidate) || !LastClickedTimes.TryGetValue(stateKey, out lastClickedTime))
        {
            return false;
        }

        return lastClickedCandidate == candidate && EditorApplication.timeSinceStartup - lastClickedTime <= DoubleClickThresholdSeconds;
    }

    private static void RegisterClick(string stateKey, string candidate)
    {
        LastClickedEventIds[stateKey] = candidate;
        LastClickedTimes[stateKey] = EditorApplication.timeSinceStartup;
    }

    private static List<string> FilterEventIds(List<string> eventIds, string query)
    {
        List<string> filtered = new List<string>();
        string normalizedQuery = string.IsNullOrWhiteSpace(query) ? string.Empty : query.Trim();
        for (int index = 0; index < eventIds.Count; index += 1)
        {
            string eventId = eventIds[index];
            if (string.IsNullOrEmpty(normalizedQuery) || eventId.IndexOf(normalizedQuery, StringComparison.OrdinalIgnoreCase) >= 0)
            {
                filtered.Add(eventId);
            }
        }
        return filtered;
    }
}
