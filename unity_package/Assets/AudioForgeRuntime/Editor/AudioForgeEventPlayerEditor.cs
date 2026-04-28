using UnityEditor;
using UnityEngine;

[CanEditMultipleObjects]

[CustomEditor(typeof(AudioForgeEventPlayer))]
public sealed class AudioForgeEventPlayerEditor : Editor
{
    private static bool _showAdvancedSettings;

    public override void OnInspectorGUI()
    {
        serializedObject.Update();

        DrawCommonSection();
        EditorGUILayout.Space(8f);
        DrawTriggerSection();
        EditorGUILayout.Space(8f);
        DrawAdvancedSection();

        serializedObject.ApplyModifiedProperties();
    }

    private void DrawCommonSection()
    {
        SerializedProperty eventIdProperty = serializedObject.FindProperty("EventId");
        AudioForgeEventIdSearchInspector.DrawEventIdField(serializedObject, eventIdProperty, target.GetInstanceID() + "/event-player");

        AudioForgeEditorEventSummary summary = AudioForgeEventIdEditorUtility.GetEventSummary(eventIdProperty.stringValue);
        EditorGUILayout.LabelField("常用配置", EditorStyles.boldLabel);
        if (summary != null)
        {
            EditorGUILayout.BeginVertical(EditorStyles.helpBox);
            DrawReadOnlyRow("事件 ID", summary.EventId);
            DrawReadOnlyRow("所属总线", summary.BusName);
            DrawReadOnlyRow("导出基线", summary.VolumeDb.ToString("0.##") + " dB");
            DrawReadOnlyRow("播放模式", summary.PlayMode + " / Clip " + summary.ClipCount);
            EditorGUILayout.EndVertical();
        }
        else
        {
            EditorGUILayout.HelpBox("当前事件还没有在 AudioData.json 中找到对应导出信息。", MessageType.Info);
        }

        EditorGUILayout.PropertyField(serializedObject.FindProperty("Runtime"), new GUIContent("运行时引用"));
        EditorGUILayout.Slider(serializedObject.FindProperty("LocalEventVolumeDbOffset"), -24f, 12f, new GUIContent("当前组件偏移", "单位 dB。只影响这个组件触发的当前事件。"));
    }

    private void DrawTriggerSection()
    {
        EditorGUILayout.LabelField("触发方式", EditorStyles.boldLabel);
        EditorGUILayout.PropertyField(serializedObject.FindProperty("PlayOnStart"), new GUIContent("启动时播放"));
        EditorGUILayout.PropertyField(serializedObject.FindProperty("TriggerOnEnable"), new GUIContent("启用时播放"));
        EditorGUILayout.PropertyField(serializedObject.FindProperty("TriggerKey"), new GUIContent("触发按键"));
    }

    private void DrawAdvancedSection()
    {
        _showAdvancedSettings = EditorGUILayout.Foldout(_showAdvancedSettings, "低频配置", true);
        if (!_showAdvancedSettings)
        {
            return;
        }

        EditorGUILayout.PropertyField(serializedObject.FindProperty("UseAttachedAudioSource"), new GUIContent("使用挂载的 AudioSource"));
    }

    private void DrawReadOnlyRow(string label, string value)
    {
        EditorGUILayout.BeginHorizontal();
        EditorGUILayout.PrefixLabel(label);
        EditorGUILayout.SelectableLabel(string.IsNullOrWhiteSpace(value) ? "-" : value, EditorStyles.textField, GUILayout.Height(EditorGUIUtility.singleLineHeight));
        EditorGUILayout.EndHorizontal();
    }
}
