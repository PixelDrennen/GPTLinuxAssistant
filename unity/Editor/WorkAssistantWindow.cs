using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading.Tasks;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Object = UnityEngine.Object;

namespace WorkAssistant
{
    public sealed class WorkAssistantWindow : EditorWindow
    {
        private static readonly HttpClient Client = new HttpClient(new HttpClientHandler
        {
            UseProxy = false,
            AllowAutoRedirect = false
        }) { Timeout = TimeSpan.FromSeconds(3) };

        private MonoBehaviour source;
        private Object destination;
        private string field = "";
        private bool sharing;
        private bool closed;
        private string status = "Open a prefab in Prefab Mode and choose the reference to connect.";

        [MenuItem("Tools/GPT Linux Assistant")]
        public static void Open() => GetWindow<WorkAssistantWindow>("Work Assistant");

        private void OnEnable() => closed = false;

        private void OnDisable() => closed = true;

        private void OnGUI()
        {
            EditorGUILayout.HelpBox(status, MessageType.Info);
            using (new EditorGUI.DisabledScope(sharing))
            {
                source = (MonoBehaviour)EditorGUILayout.ObjectField("Source component", source, typeof(MonoBehaviour), true);
                if (GUILayout.Button("Use component on selected object") && Selection.activeGameObject != null)
                    source = Selection.activeGameObject.GetComponent<MonoBehaviour>();
                var fields = ReferenceFields();
                if (!fields.Contains(field))
                    field = "";
                fields.Insert(0, "Choose an empty reference");
                int selected = EditorGUILayout.Popup("Reference field", Math.Max(0, fields.IndexOf(field)), fields.ToArray());
                field = selected > 0 ? fields[selected] : "";
                var fieldType = SourceFieldType(field);
                destination = EditorGUILayout.ObjectField("Destination", destination, fieldType ?? typeof(Object), true);
                using (new EditorGUI.DisabledScope(!source || !destination || fieldType == null))
                {
                    if (GUILayout.Button("Share Unity connection"))
                        Share();
                }
            }
        }

        private Type SourceFieldType(string property)
        {
            if (!source || string.IsNullOrEmpty(property))
                return null;
            for (Type type = source.GetType(); type != null && type != typeof(MonoBehaviour); type = type.BaseType)
            {
                const System.Reflection.BindingFlags Flags = System.Reflection.BindingFlags.Instance |
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic |
                    System.Reflection.BindingFlags.DeclaredOnly;
                var member = type.GetField(property, Flags);
                if (member != null && typeof(Object).IsAssignableFrom(member.FieldType))
                    return member.FieldType;
            }
            return null;
        }

        private List<string> ReferenceFields()
        {
            var fields = new List<string>();
            // Keep the captured field visible while waiting if another editor assigns it.
            if (sharing)
            {
                fields.Add(field);
                return fields;
            }
            if (!source)
                return fields;
            using (var serialized = new SerializedObject(source))
            using (var iterator = serialized.GetIterator())
            {
                bool enter = true;
                while (iterator.NextVisible(enter))
                {
                    enter = false;
                    if (iterator.propertyType == SerializedPropertyType.ObjectReference &&
                        iterator.objectReferenceInstanceIDValue == 0 && SourceFieldType(iterator.propertyPath) != null)
                        fields.Add(iterator.propertyPath);
                }
            }
            return fields;
        }

        private async void Share()
        {
            var stage = PrefabStageUtility.GetCurrentPrefabStage();
            if (!Inside(stage, source) || !Inside(stage, destination) || !SourceFieldType(field).IsInstanceOfType(destination))
            {
                status = "Choose compatible objects inside the same open prefab.";
                return;
            }
            var target = new Capture
            {
                Stage = stage,
                Path = stage.assetPath,
                Source = source,
                Destination = destination,
                SourceLabel = Describe(source),
                DestinationLabel = Describe(destination),
                Field = field,
                Revision = EditorJsonUtility.ToJson(source),
                Id = Guid.NewGuid().ToString("N")
            };
            sharing = true;
            try
            {
                string runtime = Environment.GetEnvironmentVariable("XDG_RUNTIME_DIR");
                if (string.IsNullOrWhiteSpace(runtime))
                    throw new IOException("XDG_RUNTIME_DIR is unavailable.");
                string[] endpoint = File.ReadAllLines(System.IO.Path.Combine(runtime, "gpt-linux-assistant.endpoint"));
                if (endpoint.Length != 2 || !int.TryParse(endpoint[0], out int port) || port < 1 || port > 65535 ||
                    !System.Text.RegularExpressions.Regex.IsMatch(endpoint[1], "^[a-f0-9]{64}$"))
                    throw new IOException("The assistant endpoint is invalid.");
                target.Port = port;
                target.Token = endpoint[1];
                await Send(target, "/capture", new Message
                {
                    label = target.Path,
                    data = new Reference
                    {
                        source = target.SourceLabel,
                        field = target.Field,
                        destination = target.DestinationLabel
                    }
                });
                status = "Connection shared. Review it in GPT Linux Assistant.";
                Repaint();
                var until = DateTime.UtcNow.AddSeconds(190);
                while (!closed && this && DateTime.UtcNow < until)
                {
                    await Task.Delay(400);
                    if (closed || !this)
                        return;
                    var reply = await Send(target, "/poll", new Message());
                    if (!string.IsNullOrEmpty(reply.id))
                    {
                        string outcome;
                        try
                        {
                            outcome = !closed && this && Apply(target) ? "applied" : "stale";
                        }
                        catch (Exception exception)
                        {
                            Debug.LogException(exception);
                            outcome = "failed";
                        }
                        status = outcome == "applied" ? "Connection applied. Use Unity Undo to revert." :
                            "Connection skipped or failed. Check the source and editability.";
                        await Send(target, "/finish", new Message { id = reply.id, outcome = outcome });
                        return;
                    }
                    if (!reply.waiting)
                        break;
                }
                status = "Sharing ended.";
            }
            catch (Exception exception)
            {
                status = exception.Message;
            }
            finally
            {
                sharing = false;
                if (this)
                    Repaint();
            }
        }

        private bool Apply(Capture target)
        {
            string projectFolder = System.IO.Path.GetDirectoryName(Application.dataPath);
            string assetFile = System.IO.Path.Combine(projectFolder, target.Path);
            if (!ReferenceEquals(target.Stage, PrefabStageUtility.GetCurrentPrefabStage()) ||
                target.Stage.assetPath != target.Path || !Inside(target.Stage, target.Source) ||
                !Inside(target.Stage, target.Destination) || Describe(target.Source) != target.SourceLabel ||
                Describe(target.Destination) != target.DestinationLabel ||
                EditorJsonUtility.ToJson(target.Source) != target.Revision ||
                !AssetDatabase.IsOpenForEdit(target.Path, StatusQueryOptions.ForceUpdate) ||
                !File.Exists(assetFile) || new FileInfo(assetFile).IsReadOnly)
                return false;

            using (var serialized = new SerializedObject(target.Source))
            {
                var reference = serialized.FindProperty(target.Field);
                if (reference == null || reference.propertyType != SerializedPropertyType.ObjectReference ||
                    !reference.editable || reference.objectReferenceInstanceIDValue != 0)
                    return false;

                Undo.IncrementCurrentGroup();
                int group = Undo.GetCurrentGroup();
                Undo.SetCurrentGroupName("Connect dialogue reference");
                try
                {
                    reference.objectReferenceValue = target.Destination;
                    if (!serialized.ApplyModifiedProperties())
                        return false;
                    serialized.Update();
                    if (serialized.FindProperty(target.Field).objectReferenceValue != target.Destination)
                    {
                        Undo.RevertAllDownToGroup(group);
                        return false;
                    }
                    Undo.CollapseUndoOperations(group);
                    return true;
                }
                catch
                {
                    Undo.RevertAllDownToGroup(group);
                    throw;
                }
            }
        }

        private static bool Inside(PrefabStage stage, Object item)
        {
            if (stage == null || !item)
                return false;
            var gameObject = item as GameObject ?? (item as Component)?.gameObject;
            return gameObject && stage.IsPartOfPrefabContents(gameObject);
        }

        private static string Describe(Object item)
        {
            var component = item as Component;
            var gameObject = component ? component.gameObject : (GameObject)item;
            var names = new Stack<string>();
            for (var current = gameObject.transform; current; current = current.parent)
                names.Push($"{current.name}[{current.GetSiblingIndex()}]");
            string path = string.Join("/", names);
            if (!component)
                return path;
            var components = gameObject.GetComponents(component.GetType());
            return $"{path} ({component.GetType().Name} {Array.IndexOf(components, component) + 1})";
        }

        private static async Task<Reply> Send(Capture target, string route, Message body)
        {
            body.kind = "unity";
            body.capture = target.Id;
            using (var request = new HttpRequestMessage(HttpMethod.Post, $"http://127.0.0.1:{target.Port}{route}"))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", target.Token);
                request.Content = new StringContent(JsonUtility.ToJson(body), Encoding.UTF8, "application/json");
                using (var response = await Client.SendAsync(request))
                {
                    var reply = JsonUtility.FromJson<Reply>(await response.Content.ReadAsStringAsync());
                    if (!response.IsSuccessStatusCode)
                        throw new IOException(reply?.error ?? "Assistant request failed.");
                    return reply ?? throw new IOException("Assistant returned an invalid reply.");
                }
            }
        }

        private sealed class Capture
        {
            public PrefabStage Stage;
            public MonoBehaviour Source;
            public Object Destination;
            public string Path, Field, Revision, Id, Token, SourceLabel, DestinationLabel;
            public int Port;
        }

        [Serializable] private sealed class Message
        {
            public string kind, capture, label, id, outcome;
            public Reference data;
        }

        [Serializable] private sealed class Reference
        {
            public string source, field, destination;
        }

        [Serializable] private sealed class Reply
        {
            public bool waiting;
            public string id, error;
        }
    }
}
