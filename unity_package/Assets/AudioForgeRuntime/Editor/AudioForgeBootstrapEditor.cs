using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(AudioForgeBootstrap))]
[CanEditMultipleObjects]
public sealed class AudioForgeBootstrapEditor : Editor
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
        AudioForgeEventIdSearchInspector.DrawEventIdField(serializedObject, eventIdProperty, target.GetInstanceID() + "/bootstrap");

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

        EditorGUILayout.Slider(serializedObject.FindProperty("LocalEventVolumeDbOffset"), -24f, 12f, new GUIContent("当前组件偏移", "单位 dB。只影响 Bootstrap 触发的当前事件。"));
    }

    private void DrawTriggerSection()
    {
        EditorGUILayout.LabelField("触发方式", EditorStyles.boldLabel);
        EditorGUILayout.PropertyField(serializedObject.FindProperty("AutoPlayOnStart"), new GUIContent("启动时自动播放"));
        EditorGUILayout.PropertyField(serializedObject.FindProperty("TriggerKey"), new GUIContent("触发按键"));
    }

    private void DrawAdvancedSection()
    {
        _showAdvancedSettings = EditorGUILayout.Foldout(_showAdvancedSettings, "低频配置", true);
        if (!_showAdvancedSettings)
        {
            return;
        }

        EditorGUILayout.HelpBox("Bootstrap 会自动准备 Runtime 和 EventPlayer。更细的运行时、总线和项目级事件微调，请在 AudioForgeRuntime 上配置。", MessageType.None);
    }

    private void DrawReadOnlyRow(string label, string value)
    {
        EditorGUILayout.BeginHorizontal();
        EditorGUILayout.PrefixLabel(label);
        EditorGUILayout.SelectableLabel(string.IsNullOrWhiteSpace(value) ? "-" : value, EditorStyles.textField, GUILayout.Height(EditorGUIUtility.singleLineHeight));
        EditorGUILayout.EndHorizontal();
    }
}
