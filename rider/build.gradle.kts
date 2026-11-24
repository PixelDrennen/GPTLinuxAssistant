plugins {
    java
    id("org.jetbrains.intellij.platform") version "2.19.0"
}

group = "io.github.pixeldrennen"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform { defaultRepositories() }
}

dependencies {
    intellijPlatform {
        rider(providers.gradleProperty("riderVersion").orElse("2026.2"))
    }
}

java {
    toolchain.languageVersion = JavaLanguageVersion.of(21)
}

intellijPlatform {
    pluginConfiguration {
        ideaVersion {
            sinceBuild = "253"
        }
    }
}
