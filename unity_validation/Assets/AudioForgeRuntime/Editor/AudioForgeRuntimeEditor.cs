using UnityEditor;
using UnityEngine;
using UnityEngine.Audio;

[CanEditMultipleObjects]

[CustomEditor(typeof(AudioForgeRuntime))]
public sealed class AudioForgeRuntimeEditor : Editor
{
    private static bool _showBusOverview = true;
    private static bool _showEventOverview = true;
    private static bool _showAdvancedConfig;
    private static bool _showRawBindings;

    public override void OnInspectorGUI()
    {
        serializedObject.Update();

        DrawHeaderSummary();
        EditorGUILayout.Space(8f);
        DrawPrimaryConfiguration();
        EditorGUILayout.Space(8f);
        DrawBusOverview();
        EditorGUILayout.Space(8f);
        DrawEventOverview();
        EditorGUILayout.Space(8f);
        DrawMixerRuntimePanel();
        EditorGUILayout.Space(8f);
        DrawAdvancedConfiguration();

        serializedObject.ApplyModifiedProperties();
    }

    private void DrawHeaderSummary()
    {
        AudioForgeRuntime runtime = target as AudioForgeRuntime;
        AudioForgeEditorAudioDataSummary summary = AudioForgeEventIdEditorUtility.GetAudioDataSummary();

        EditorGUILayout.LabelField("AudioForge 音频管理", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox("上方突出常用信息和总线微调；低频运行时参数与原始绑定列表收纳到折叠区。", MessageType.Info);

        if (!summary.Exists)
        {
            string message = string.IsNullOrWhiteSpace(summary.ParseError)
                ? "未找到 StreamingAssets/AudioForge/AudioData.json。当前无法自动识别 AudioForge 导出总线。"
                : "AudioData.json 解析失败：" + summary.ParseError;
            EditorGUILayout.HelpBox(message, MessageType.Warning);
            return;
        }

        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        DrawReadOnlyRow("导出项目", string.IsNullOrWhiteSpace(summary.ProjectName) ? "未命名" : summary.ProjectName);
        DrawReadOnlyRow("运行时格式", string.IsNullOrWhiteSpace(summary.RuntimeAudioFormat) ? "未标记" : summary.RuntimeAudioFormat);
        DrawReadOnlyRow("事件数量", summary.EventCount.ToString());
        DrawReadOnlyRow("总线数量", summary.BusCount.ToString());
        if (runtime != null)
        {
            DrawReadOnlyRow("运行时状态", runtime.IsReady ? "已初始化" : "未初始化");
        }
        EditorGUILayout.EndVertical();

        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("刷新 Event ID 枚举", GUILayout.Height(24f)))
        {
            AudioForgeEventIdEditorUtility.RefreshAudioEventIdFromStreamingAssets();
        }
        if (GUILayout.Button("定位 AudioData.json", GUILayout.Height(24f)))
        {
            Object audioDataAsset = AssetDatabase.LoadAssetAtPath<Object>("Assets/StreamingAssets/AudioForge/AudioData.json");
            if (audioDataAsset != null)
            {
                EditorGUIUtility.PingObject(audioDataAsset);
                Selection.activeObject = audioDataAsset;
            }
            else
            {
                EditorUtility.DisplayDialog("AudioForge", "当前工程里还没有导入 Assets/StreamingAssets/AudioForge/AudioData.json。", "确定");
            }
        }
        EditorGUILayout.EndHorizontal();
    }

    private void DrawPrimaryConfiguration()
    {
        SerializedProperty integrateProperty = serializedObject.FindProperty("integrateWithUnityAudioMixer");
        SerializedProperty defaultOutputProperty = serializedObject.FindProperty("defaultOutputMixerGroup");
        SerializedProperty masterTweakProperty = serializedObject.FindProperty("unityMasterVolume");

        EditorGUILayout.LabelField("常用配置", EditorStyles.boldLabel);
        EditorGUILayout.PropertyField(integrateProperty, new GUIContent("启用 Unity AudioMixer 集成", "关闭后仅保留 AudioForge 导出基线，不走 Unity AudioMixer 路由。"));
        using (new EditorGUI.DisabledScope(!integrateProperty.boolValue))
        {
            EditorGUILayout.PropertyField(defaultOutputProperty, new GUIContent("默认输出组", "未单独映射的 AudioForge 总线会落到这里。"));
            EditorGUILayout.Slider(masterTweakProperty, 0f, 1f, new GUIContent("主总线附加倍率", "1 表示不改动 AudioForge 导出结果；小于 1 表示在 Unity 侧整体压低。"));
        }
    }

    private void DrawBusOverview()
    {
        SerializedProperty integrateProperty = serializedObject.FindProperty("integrateWithUnityAudioMixer");
        SerializedProperty bindingsProperty = serializedObject.FindProperty("unityBusMixerBindings");
        AudioForgeRuntime runtime = target as AudioForgeRuntime;
        System.Collections.Generic.List<AudioForgeEditorBusSummary> busSummaries = AudioForgeEventIdEditorUtility.GetAvailableBusSummaries();

        _showBusOverview = EditorGUILayout.Foldout(_showBusOverview, "常用总线信息与微调", true);
        if (!_showBusOverview)
        {
            return;
        }

        if (busSummaries.Count == 0)
        {
            EditorGUILayout.HelpBox("当前还没有可识别的 AudioForge 总线。请先导入 AudioData.json。", MessageType.Info);
            return;
        }

        EditorGUILayout.HelpBox("这里直接显示 AudioForge 导出总线、Unity 映射状态和附加倍率。附加倍率为 1 时表示未改动。", MessageType.None);
        for (int index = 0; index < busSummaries.Count; index += 1)
        {
            AudioForgeEditorBusSummary summary = busSummaries[index];
            int bindingIndex = EnsureBindingIndex(bindingsProperty, summary.BusName);
            SerializedProperty bindingProperty = bindingsProperty.GetArrayElementAtIndex(bindingIndex);
            SerializedProperty busNameProperty = bindingProperty.FindPropertyRelative("BusName");
            SerializedProperty outputGroupProperty = bindingProperty.FindPropertyRelative("OutputMixerGroup");
            SerializedProperty volumeProperty = bindingProperty.FindPropertyRelative("Volume");
            if (string.IsNullOrWhiteSpace(busNameProperty.stringValue))
            {
                busNameProperty.stringValue = summary.BusName;
            }

            bool isTweaked = !Mathf.Approximately(volumeProperty.floatValue, 1f);
            string mappingStatus = BuildMappingStatus(runtime, summary.BusName, integrateProperty.boolValue, outputGroupProperty.objectReferenceValue as AudioMixerGroup);
            string tweakStatus = isTweaked ? "已微调" : "未改动";

            EditorGUILayout.BeginVertical(EditorStyles.helpBox);
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField(summary.BusName, EditorStyles.boldLabel);
            GUILayout.FlexibleSpace();
            EditorGUILayout.LabelField(tweakStatus + " / " + mappingStatus, GUILayout.Width(170f));
            EditorGUILayout.EndHorizontal();

            DrawReadOnlyRow("父总线", summary.ParentBusName);
            DrawReadOnlyRow("导出基线", summary.IsMuted ? "静音" : summary.VolumeDb.ToString("0.##") + " dB");
            if (runtime != null && Application.isPlaying && runtime.IsReady)
            {
                DrawReadOnlyRow("当前有效值", runtime.GetEffectiveBusVolume(summary.BusName).ToString("0.###"));
            }
            else
            {
                float predictedEffectiveValue = summary.LinearVolume * serializedObject.FindProperty("unityMasterVolume").floatValue * volumeProperty.floatValue;
                DrawReadOnlyRow("预估有效值", predictedEffectiveValue.ToString("0.###"));
            }

            using (new EditorGUI.DisabledScope(!integrateProperty.boolValue))
            {
                EditorGUILayout.PropertyField(outputGroupProperty, new GUIContent("映射输出组", "为空时会使用上面的默认输出组。"));
                DrawTweakSlider(runtime, summary.BusName, volumeProperty);
            }

            EditorGUILayout.EndVertical();
        }
    }

    private void DrawEventOverview()
    {
        SerializedProperty eventBindingsProperty = serializedObject.FindProperty("unityEventVolumeBindings");
        AudioForgeRuntime runtime = target as AudioForgeRuntime;
        System.Collections.Generic.List<AudioForgeEditorEventSummary> eventSummaries = AudioForgeEventIdEditorUtility.GetAvailableEventSummaries();

        _showEventOverview = EditorGUILayout.Foldout(_showEventOverview, "事件微调", true);
        if (!_showEventOverview)
        {
            return;
        }

        if (eventSummaries.Count == 0)
        {
            EditorGUILayout.HelpBox("当前还没有可识别的 AudioForge 事件。请先导入 AudioData.json。", MessageType.Info);
            return;
        }

        EditorGUILayout.HelpBox("这里管理项目级事件微调。0 dB 表示未改动 AudioForge 导出事件基线；组件级偏移请在 AudioForgeEventPlayer 上单独设置。", MessageType.None);
        for (int index = 0; index < eventSummaries.Count; index += 1)
        {
            AudioForgeEditorEventSummary summary = eventSummaries[index];
            int bindingIndex = EnsureEventBindingIndex(eventBindingsProperty, summary.EventId);
            SerializedProperty bindingProperty = eventBindingsProperty.GetArrayElementAtIndex(bindingIndex);
            SerializedProperty eventIdProperty = bindingProperty.FindPropertyRelative("EventId");
            SerializedProperty volumeOffsetProperty = bindingProperty.FindPropertyRelative("VolumeDbOffset");
            if (string.IsNullOrWhiteSpace(eventIdProperty.stringValue))
            {
                eventIdProperty.stringValue = summary.EventId;
            }

            bool isTweaked = !Mathf.Approximately(volumeOffsetProperty.floatValue, 0f);
            EditorGUILayout.BeginVertical(EditorStyles.helpBox);
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField(summary.EventId, EditorStyles.boldLabel);
            GUILayout.FlexibleSpace();
            EditorGUILayout.LabelField(isTweaked ? "已微调" : "未改动", GUILayout.Width(70f));
            EditorGUILayout.EndHorizontal();
            DrawReadOnlyRow("所属总线", summary.BusName);
            DrawReadOnlyRow("导出基线", summary.VolumeDb.ToString("0.##") + " dB");
            DrawReadOnlyRow("播放模式", summary.PlayMode + " / Clip " + summary.ClipCount);
            DrawEventDbSlider(runtime, summary.EventId, volumeOffsetProperty);
            EditorGUILayout.EndVertical();
        }
    }

    private void DrawMixerRuntimePanel()
    {
        AudioForgeRuntime runtime = target as AudioForgeRuntime;
        if (runtime == null)
        {
            return;
        }

        EditorGUILayout.LabelField("运行中快速微调", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox("这里只保留运行中常用操作：主总线附加倍率和各总线附加倍率实时微调。", MessageType.Info);

        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("进入 Play 模式后，这里会显示实时滑杆。编辑态下请在上面的“常用总线信息与微调”区域维护配置。", MessageType.None);
            return;
        }

        if (!runtime.IsReady)
        {
            EditorGUILayout.HelpBox("Runtime 尚未初始化，先运行场景或确认 AudioData.json 已成功加载。", MessageType.Warning);
            return;
        }

        float masterVolume = EditorGUILayout.Slider("主总线附加倍率", runtime.GetUnityMasterVolume(), 0f, 1f);
        if (!Mathf.Approximately(masterVolume, runtime.GetUnityMasterVolume()))
        {
            runtime.SetUnityMasterVolume(masterVolume);
            EditorUtility.SetDirty(runtime);
        }

        System.Collections.Generic.List<string> busNames = runtime.GetBusNames();
        for (int index = 0; index < busNames.Count; index += 1)
        {
            string busName = busNames[index];
            float busVolume = runtime.GetUnityBusVolume(busName);
            float updatedBusVolume = EditorGUILayout.Slider(busName + " 附加倍率", busVolume, 0f, 1f);
            if (!Mathf.Approximately(updatedBusVolume, busVolume))
            {
                runtime.SetUnityBusVolume(busName, updatedBusVolume);
                EditorUtility.SetDirty(runtime);
            }
        }
    }

    private void DrawAdvancedConfiguration()
    {
        _showAdvancedConfig = EditorGUILayout.Foldout(_showAdvancedConfig, "低频配置", true);
        if (_showAdvancedConfig)
        {
            EditorGUILayout.PropertyField(serializedObject.FindProperty("persistAcrossScenes"), new GUIContent("跨场景常驻"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("prewarmedSourcesPerBus"), new GUIContent("每总线预热声源数"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("maxSourcesPerBus"), new GUIContent("每总线最大声源数"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("masterBusName"), new GUIContent("主总线名称"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("useReferenceTimePreservingPitch"), new GUIContent("启用参考保时长变调"));
        }

        _showRawBindings = EditorGUILayout.Foldout(_showRawBindings, "原始绑定列表", true);
        if (_showRawBindings)
        {
            EditorGUILayout.PropertyField(serializedObject.FindProperty("unityBusMixerBindings"), new GUIContent("绑定明细"), true);
            EditorGUILayout.PropertyField(serializedObject.FindProperty("unityEventVolumeBindings"), new GUIContent("事件微调明细"), true);
        }
    }

    private void DrawReadOnlyRow(string label, string value)
    {
        EditorGUILayout.BeginHorizontal();
        EditorGUILayout.PrefixLabel(label);
        EditorGUILayout.SelectableLabel(string.IsNullOrWhiteSpace(value) ? "-" : value, EditorStyles.textField, GUILayout.Height(EditorGUIUtility.singleLineHeight));
        EditorGUILayout.EndHorizontal();
    }

    private void DrawTweakSlider(AudioForgeRuntime runtime, string busName, SerializedProperty volumeProperty)
    {
        EditorGUI.BeginChangeCheck();
        float updatedValue = EditorGUILayout.Slider(new GUIContent("附加倍率", "1 表示未改动 AudioForge 导出总线；小于 1 表示在 Unity 侧额外压低。"), volumeProperty.floatValue, 0f, 1f);
        if (!EditorGUI.EndChangeCheck())
        {
            return;
        }

        volumeProperty.floatValue = updatedValue;
        if (runtime != null && Application.isPlaying && runtime.IsReady)
        {
            runtime.SetUnityBusVolume(busName, updatedValue);
            EditorUtility.SetDirty(runtime);
        }
    }

    private int EnsureBindingIndex(SerializedProperty bindingsProperty, string busName)
    {
        for (int index = 0; index < bindingsProperty.arraySize; index += 1)
        {
            SerializedProperty element = bindingsProperty.GetArrayElementAtIndex(index);
            SerializedProperty busNameProperty = element.FindPropertyRelative("BusName");
            if (string.Equals(busNameProperty.stringValue, busName, System.StringComparison.OrdinalIgnoreCase))
            {
                return index;
            }
        }

        int newIndex = bindingsProperty.arraySize;
        bindingsProperty.InsertArrayElementAtIndex(newIndex);
        SerializedProperty createdElement = bindingsProperty.GetArrayElementAtIndex(newIndex);
        createdElement.FindPropertyRelative("BusName").stringValue = busName;
        createdElement.FindPropertyRelative("OutputMixerGroup").objectReferenceValue = null;
        createdElement.FindPropertyRelative("Volume").floatValue = 1f;
        return newIndex;
    }

    private int EnsureEventBindingIndex(SerializedProperty bindingsProperty, string eventId)
    {
        for (int index = 0; index < bindingsProperty.arraySize; index += 1)
        {
            SerializedProperty element = bindingsProperty.GetArrayElementAtIndex(index);
            SerializedProperty eventIdProperty = element.FindPropertyRelative("EventId");
            if (string.Equals(eventIdProperty.stringValue, eventId, System.StringComparison.Ordinal))
            {
                return index;
            }
        }

        int newIndex = bindingsProperty.arraySize;
        bindingsProperty.InsertArrayElementAtIndex(newIndex);
        SerializedProperty createdElement = bindingsProperty.GetArrayElementAtIndex(newIndex);
        createdElement.FindPropertyRelative("EventId").stringValue = eventId;
        createdElement.FindPropertyRelative("VolumeDbOffset").floatValue = 0f;
        return newIndex;
    }

    private void DrawEventDbSlider(AudioForgeRuntime runtime, string eventId, SerializedProperty volumeOffsetProperty)
    {
        EditorGUI.BeginChangeCheck();
        float updatedValue = EditorGUILayout.Slider(new GUIContent("项目级偏移", "单位 dB。0 表示不改动 AudioForge 事件基线。"), volumeOffsetProperty.floatValue, -24f, 12f);
        if (!EditorGUI.EndChangeCheck())
        {
            return;
        }

        volumeOffsetProperty.floatValue = updatedValue;
        if (runtime != null && Application.isPlaying && runtime.IsReady)
        {
            runtime.SetUnityEventVolumeOffsetDb(eventId, updatedValue);
            EditorUtility.SetDirty(runtime);
        }
    }

    private string BuildMappingStatus(AudioForgeRuntime runtime, string busName, bool integrateWithMixer, AudioMixerGroup configuredGroup)
    {
        if (!integrateWithMixer)
        {
            return "未启用 Mixer";
        }

        AudioMixerGroup runtimeGroup = runtime != null && Application.isPlaying && runtime.IsReady
            ? runtime.GetBusOutputMixerGroup(busName)
            : configuredGroup;
        if (runtimeGroup != null)
        {
            return "已映射";
        }

        return "默认输出组";
    }
}
