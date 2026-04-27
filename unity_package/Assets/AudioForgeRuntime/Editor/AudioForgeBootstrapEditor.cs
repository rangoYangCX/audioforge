using UnityEditor;

[CustomEditor(typeof(AudioForgeBootstrap))]
[CanEditMultipleObjects]
public sealed class AudioForgeBootstrapEditor : Editor
{
    public override void OnInspectorGUI()
    {
        serializedObject.Update();

        SerializedProperty eventIdProperty = serializedObject.FindProperty("EventId");
        AudioForgeEventIdSearchInspector.DrawEventIdField(serializedObject, eventIdProperty, target.GetInstanceID() + "/bootstrap");

        DrawPropertiesExcluding(serializedObject, "m_Script", "EventId");

        serializedObject.ApplyModifiedProperties();
    }
}
