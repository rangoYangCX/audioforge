using UnityEditor;

[CustomEditor(typeof(AudioForgeEventPlayer))]
[CanEditMultipleObjects]
public sealed class AudioForgeEventPlayerEditor : Editor
{
    public override void OnInspectorGUI()
    {
        serializedObject.Update();

        SerializedProperty eventIdProperty = serializedObject.FindProperty("EventId");
        AudioForgeEventIdSearchInspector.DrawEventIdField(serializedObject, eventIdProperty, target.GetInstanceID() + "/event-player");

        DrawPropertiesExcluding(serializedObject, "m_Script", "EventId");

        serializedObject.ApplyModifiedProperties();
    }
}
