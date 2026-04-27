using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(AudioForgeRuntime))]
public sealed class AudioForgeRuntimeEditor : Editor
{
    public override void OnInspectorGUI()
    {
        serializedObject.Update();

        DrawDefaultInspector();
        EditorGUILayout.Space(8f);
        DrawMixerRuntimePanel();

        serializedObject.ApplyModifiedProperties();
    }

    private void DrawMixerRuntimePanel()
    {
        AudioForgeRuntime runtime = target as AudioForgeRuntime;
        if (runtime == null)
        {
            return;
        }

        EditorGUILayout.LabelField("Runtime Mixer Control", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox("这里用于在 Inspector 配置栏里直接调节 Unity AudioMixer 接入后的主音量和总线音量。", MessageType.Info);

        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("进入 Play 模式后，这里会显示可实时调节的主音量和总线音量。编辑态下请直接修改上面的序列化配置。", MessageType.None);
            return;
        }

        if (!runtime.IsReady)
        {
            EditorGUILayout.HelpBox("Runtime 尚未初始化，先运行场景或确认 AudioData.json 已成功加载。", MessageType.Warning);
            return;
        }

        float masterVolume = EditorGUILayout.Slider("Unity Master Volume", runtime.GetUnityMasterVolume(), 0f, 1f);
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
            float updatedBusVolume = EditorGUILayout.Slider(busName + " Volume", busVolume, 0f, 1f);
            if (!Mathf.Approximately(updatedBusVolume, busVolume))
            {
                runtime.SetUnityBusVolume(busName, updatedBusVolume);
                EditorUtility.SetDirty(runtime);
            }
        }
    }
}
