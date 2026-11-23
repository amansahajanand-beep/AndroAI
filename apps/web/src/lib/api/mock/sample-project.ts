/**
 * DEV-ONLY sample Android project used by the mock adapter so the IDE can be
 * developed without a backend. Never shipped as product content.
 */
export const SAMPLE_FILES: Record<string, string> = {
  "settings.gradle.kts": `pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Trailhead"
include(":app")
`,
  "build.gradle.kts": `plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
`,
  "gradle.properties": `org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
`,
  "gradle/libs.versions.toml": `[versions]
agp = "8.7.2"
kotlin = "2.1.0"
composeBom = "2024.12.01"

[libraries]
androidx-compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }
androidx-material3 = { group = "androidx.compose.material3", name = "material3" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
`,
  "app/build.gradle.kts": `plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.trailhead.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.trailhead.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.3.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    buildFeatures { compose = true }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.material3)
    testImplementation("junit:junit:4.13.2")
}

apply(from = "jacoco.gradle")
`,
  "app/jacoco.gradle": `// Legacy Groovy script kept for coverage reports
apply plugin: 'jacoco'

tasks.register('jacocoTestReport', JacocoReport) {
    dependsOn 'testDebugUnitTest'
    reports {
        xml.required = true
        html.required = true
    }
}
`,
  "app/proguard-rules.pro": `-keep class com.trailhead.app.data.** { *; }
`,
  "app/src/main/AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />

    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:theme="@style/Theme.Trailhead">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
`,
  "app/src/main/java/com/trailhead/app/MainActivity.kt": `package com.trailhead.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.trailhead.app.data.TrailRepository
import com.trailhead.app.ui.TrailListScreen
import com.trailhead.app.ui.theme.TrailheadTheme

class MainActivity : ComponentActivity() {
    private val repository = TrailRepository()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            TrailheadTheme {
                TrailListScreen(trails = repository.trails())
            }
        }
    }
}
`,
  "app/src/main/java/com/trailhead/app/data/TrailRepository.kt": `package com.trailhead.app.data

data class Trail(
    val id: String,
    val name: String,
    val distanceKm: Double,
    val elevationGainM: Int,
    val difficulty: Difficulty,
)

enum class Difficulty { EASY, MODERATE, HARD }

class TrailRepository {
    fun trails(): List<Trail> = listOf(
        Trail("t1", "Cedar Ridge Loop", 6.4, 310, Difficulty.MODERATE),
        Trail("t2", "Lakeshore Path", 3.1, 40, Difficulty.EASY),
        Trail("t3", "Summit Traverse", 14.8, 1120, Difficulty.HARD),
    )

    fun search(query: String): List<Trail> =
        trails().filter { it.name.contains(query, ignoreCase = true) }
}
`,
  "app/src/main/java/com/trailhead/app/ui/TrailListScreen.kt": `package com.trailhead.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.trailhead.app.data.Trail
import com.trailhead.app.util.DistanceFormatter

@Composable
fun TrailListScreen(trails: List<Trail>, modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(16.dp)) {
        Text(text = "Nearby trails")
        LazyColumn {
            items(trails, key = { it.id }) { trail ->
                ListItem(
                    headlineContent = { Text(trail.name) },
                    supportingContent = {
                        Text(DistanceFormatter.format(trail.distanceKm) + " · " + trail.difficulty.name.lowercase())
                    },
                )
            }
        }
    }
}
`,
  "app/src/main/java/com/trailhead/app/ui/theme/Theme.kt": `package com.trailhead.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Forest = Color(0xFF2F5D50)
private val Moss = Color(0xFF8DB580)

@Composable
fun TrailheadTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(primary = Moss, secondary = Forest),
        content = content,
    )
}
`,
  "app/src/main/java/com/trailhead/app/util/DistanceFormatter.java": `package com.trailhead.app.util;

import java.util.Locale;

public final class DistanceFormatter {
    private DistanceFormatter() {}

    public static String format(double km) {
        if (km < 1.0) {
            return String.format(Locale.US, "%d m", Math.round(km * 1000));
        }
        return String.format(Locale.US, "%.1f km", km);
    }
}
`,
  "app/src/main/res/values/strings.xml": `<resources>
    <string name="app_name">Trailhead</string>
    <string name="search_hint">Search trails</string>
</resources>
`,
  "app/src/main/res/values/themes.xml": `<resources>
    <style name="Theme.Trailhead" parent="android:Theme.Material.NoActionBar" />
</resources>
`,
  "app/src/main/res/raw/trail_seed.json": `{
  "version": 1,
  "trails": [
    { "id": "t1", "name": "Cedar Ridge Loop", "distanceKm": 6.4 },
    { "id": "t2", "name": "Lakeshore Path", "distanceKm": 3.1 }
  ]
}
`,
  "app/src/test/java/com/trailhead/app/data/TrailRepositoryTest.kt": `package com.trailhead.app.data

import org.junit.Assert.assertEquals
import org.junit.Test

class TrailRepositoryTest {
    private val repo = TrailRepository()

    @Test
    fun searchIsCaseInsensitive() {
        assertEquals(1, repo.search("cedar").size)
    }

    @Test
    fun searchWithNoMatchReturnsEmpty() {
        assertEquals(0, repo.search("glacier").size)
    }
}
`,
  ".github/workflows/android.yml": `name: Android CI
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: 17
      - run: ./gradlew assembleDebug testDebugUnitTest
`,
  "README.md": `# Trailhead

A small Jetpack Compose app that lists nearby hiking trails.

## Modules

- \`app\` — Compose UI, data layer, unit tests

## Build

\`\`\`bash
./gradlew assembleDebug
\`\`\`
`,
};

/** Proposed change used by the mock agent to exercise diff review. */
export const SAMPLE_CHANGE = {
  modifiedPath: "app/src/main/java/com/trailhead/app/ui/TrailListScreen.kt",
  addedPath: "app/src/main/java/com/trailhead/app/ui/TrailSearchBar.kt",
  addedContent: `package com.trailhead.app.ui

import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.trailhead.app.R

@Composable
fun TrailSearchBar(query: String, onQueryChange: (String) -> Unit, modifier: Modifier = Modifier) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        placeholder = { Text(stringResource(R.string.search_hint)) },
        singleLine = true,
        modifier = modifier,
    )
}
`,
  modify(original: string) {
    return original
      .replace(
        "import androidx.compose.runtime.Composable\n",
        "import androidx.compose.runtime.Composable\nimport androidx.compose.runtime.getValue\nimport androidx.compose.runtime.mutableStateOf\nimport androidx.compose.runtime.remember\nimport androidx.compose.runtime.setValue\n",
      )
      .replace(
        "    Column(modifier = modifier.padding(16.dp)) {\n        Text(text = \"Nearby trails\")\n        LazyColumn {\n            items(trails, key = { it.id }) { trail ->",
        "    var query by remember { mutableStateOf(\"\") }\n    val visible = trails.filter { it.name.contains(query, ignoreCase = true) }\n\n    Column(modifier = modifier.padding(16.dp)) {\n        Text(text = \"Nearby trails\")\n        TrailSearchBar(query = query, onQueryChange = { query = it })\n        LazyColumn {\n            items(visible, key = { it.id }) { trail ->",
      );
  },
};
