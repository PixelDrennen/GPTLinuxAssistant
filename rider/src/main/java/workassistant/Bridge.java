package workassistant;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.SocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;

record Bridge(int port, String token) {
    private static final HttpClient CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2))
            .followRedirects(HttpClient.Redirect.NEVER)
            .proxy(new ProxySelector() {
                @Override
                public List<Proxy> select(URI uri) {
                    return List.of(Proxy.NO_PROXY);
                }

                @Override
                public void connectFailed(URI uri, SocketAddress address, IOException error) {}
            }).build();

    static Bridge connect() throws IOException {
        String runtime = System.getenv("XDG_RUNTIME_DIR");
        if (runtime == null || runtime.isBlank()) {
            throw new IOException("XDG_RUNTIME_DIR is unavailable.");
        }
        Path path = Path.of(runtime, "gpt-linux-assistant.endpoint");
        List<String> lines = Files.readAllLines(path);
        if (lines.size() != 2 || !lines.get(0).matches("[0-9]{1,5}") || !lines.get(1).matches("[a-f0-9]{64}")) {
            throw new IOException("The assistant endpoint is invalid.");
        }
        int port = Integer.parseInt(lines.get(0));
        if (port < 1 || port > 65535) {
            throw new IOException("The assistant endpoint has an invalid port.");
        }
        return new Bridge(port, lines.get(1));
    }

    JsonObject send(String route, String capture, JsonObject body) throws IOException, InterruptedException {
        body.addProperty("kind", "rider");
        body.addProperty("capture", capture);
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + route))
                .timeout(Duration.ofSeconds(3))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                .build();
        var response = CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
        JsonObject result = JsonParser.parseString(response.body()).getAsJsonObject();
        if (response.statusCode() != 200) {
            throw new IOException(result.has("error") ? result.get("error").getAsString() : "Assistant request failed.");
        }
        return result;
    }
}
