"""The Kotlin + Jetpack Compose project template (single module ``:app``).

File contents are written as they should look on disk. ``__NAME__`` marks a placeholder that
``renderer.py`` fills in (see ``renderer.placeholder_values``); everything else is literal.

Only plain Gradle Kotlin DSL, a version catalog and the Compose BOM are used. The Android Gradle
plugin is version 9, which has Kotlin built in: the Kotlin Android plugin is NOT applied (applying
it on AGP 9 is an error); only the Compose compiler plugin is. ``useAndroidX`` is on by default in
AGP 9 and is therefore not written out. ``compileSdk`` is written as the AGP 9 block, because the
pinned Compose libraries must be compiled against API 37.1 and ``compileSdk = 37`` means API 37.0
(``compileSdk { version = release(37) { minorApiLevel = 1 } }``).

The default project was built with Gradle (see ``VERIFIED_BUILD`` in ``versions.py`` for what ran).
``app/build.gradle.kts`` also enables Android resources and host (unit) tests for every variant: AGP
9.5.1 otherwise fails to create its Compose Preview tasks, so ``gradle tasks --all`` fails. This
default project has no unit test; a project rendered from a ``ProjectSpec`` gets generated
navigation tests and their test dependencies (``navtests.py``).
"""

from __future__ import annotations

from .render import TemplateFile

_SETTINGS_GRADLE = r"""pluginManagement {
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

rootProject.name = "__GRADLE_PROJECT_NAME__"
include(":app")
"""

_ROOT_BUILD_GRADLE = r"""// Top-level build file: plugins are declared here and applied in :app.

buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        // The Android Gradle plugin bundles its own Kotlin Gradle plugin. This entry makes the
        // build use the newer one that gradle/libs.versions.toml also names ("kotlin"): keep the
        // two versions equal.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:__KOTLIN__")
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
"""

_GRADLE_PROPERTIES = r"""# Project-wide Gradle settings.
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
kotlin.code.style=official
"""

_VERSION_CATALOG = r"""[versions]
agp = "__AGP__"
kotlin = "__KOTLIN__"
composeBom = "__COMPOSE_BOM__"
activityCompose = "__ACTIVITY_COMPOSE__"
navigationCompose = "__NAVIGATION_COMPOSE__"

[libraries]
androidx-compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }
androidx-compose-ui = { group = "androidx.compose.ui", name = "ui" }
androidx-compose-ui-graphics = { group = "androidx.compose.ui", name = "ui-graphics" }
androidx-compose-ui-tooling = { group = "androidx.compose.ui", name = "ui-tooling" }
androidx-compose-ui-tooling-preview = { group = "androidx.compose.ui", name = "ui-tooling-preview" }
androidx-compose-material3 = { group = "androidx.compose.material3", name = "material3" }
androidx-activity-compose = { group = "androidx.activity", name = "activity-compose", version.ref = "activityCompose" }
androidx-navigation-compose = { group = "androidx.navigation", name = "navigation-compose", version.ref = "navigationCompose" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
"""

_WRAPPER_PROPERTIES = r"""distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionSha256Sum=__GRADLE_SHA256__
distributionUrl=https\://services.gradle.org/distributions/gradle-__GRADLE__-bin.zip
networkTimeout=10000
validateDistributionUrl=true
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
"""

_APP_BUILD_GRADLE = r"""import com.android.build.api.variant.HostTestBuilder

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "__PACKAGE__"
    compileSdk {
        version = release(__COMPILE_SDK__) {
            minorApiLevel = __COMPILE_SDK_MINOR__
        }
    }

    defaultConfig {
        applicationId = "__APPLICATION_ID__"
        minSdk = __MIN_SDK__
        targetSdk = __TARGET_SDK__
        versionCode = __VERSION_CODE__
        versionName = "__VERSION_NAME__"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.__JAVA_VERSION__
        targetCompatibility = JavaVersion.__JAVA_VERSION__
    }

    buildFeatures {
        compose = true
    }

    // AGP 9 creates Compose Preview tasks for every variant. They need the Android resources in
    // unit tests (here) and unit tests enabled for every variant (androidComponents, below).
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

// Without the two settings, creating all tasks (`gradle tasks --all`) fails in the Compose Preview
// task registration. Unit tests are enabled for the release variant too; no test exists yet.
androidComponents {
    beforeVariants { variantBuilder ->
        variantBuilder.hostTests[HostTestBuilder.UNIT_TEST_TYPE]?.enable = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)
}
"""

_PROGUARD_RULES = r"""# Project-specific ProGuard / R8 rules. Release builds do not shrink code yet
# (isMinifyEnabled = false in app/build.gradle.kts), so nothing is needed here until they do.
#
# https://developer.android.com/build/shrink-code
"""

_MANIFEST = r"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <application
        android:allowBackup="false"
        android:label="@string/app_name"
        android:supportsRtl="true"
        android:theme="@style/__THEME_STYLE__">
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
"""

_STRINGS = r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">__APP_NAME__</string>
    <string name="home_message">Your app is ready to build on.</string>
</resources>
"""

_COLORS = r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="surface_light">#FFFFFBFE</color>
    <color name="surface_dark">#FF1C1B1F</color>
</resources>
"""

_THEMES = r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="__THEME_STYLE__" parent="android:Theme.Material.Light.NoActionBar">
        <item name="android:windowBackground">@color/surface_light</item>
    </style>
</resources>
"""

_THEMES_NIGHT = r"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="__THEME_STYLE__" parent="android:Theme.Material.NoActionBar">
        <item name="android:windowBackground">@color/surface_dark</item>
    </style>
</resources>
"""

_MAIN_ACTIVITY = r"""package __PACKAGE__

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import __PACKAGE__.navigation.AppNavHost
import __PACKAGE__.ui.theme.__THEME_FUNCTION__

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            __THEME_FUNCTION__ {
                AppNavHost()
            }
        }
    }
}
"""

_COLOR_KT = r"""package __PACKAGE__.ui.theme

import androidx.compose.ui.graphics.Color

val Purple80 = Color(0xFFD0BCFF)
val PurpleGrey80 = Color(0xFFCCC2DC)
val Pink80 = Color(0xFFEFB8C8)

val Purple40 = Color(0xFF6650A4)
val PurpleGrey40 = Color(0xFF625B71)
val Pink40 = Color(0xFF7D5260)
"""

_TYPE_KT = r"""package __PACKAGE__.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Typography = Typography(
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.5.sp,
    ),
)
"""

_THEME_KT = r"""package __PACKAGE__.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(
    primary = Purple80,
    secondary = PurpleGrey80,
    tertiary = Pink80,
)

private val LightColorScheme = lightColorScheme(
    primary = Purple40,
    secondary = PurpleGrey40,
    tertiary = Pink40,
)

@Composable
fun __THEME_FUNCTION__(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content,
    )
}
"""

_HOME_SCREEN = r"""package __PACKAGE__.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import __PACKAGE__.R
import __PACKAGE__.ui.theme.__THEME_FUNCTION__

@Composable
fun HomeScreen(modifier: Modifier = Modifier) {
    Scaffold(modifier = modifier.fillMaxSize()) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.headlineMedium,
            )
            Text(
                text = stringResource(R.string.home_message),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun HomeScreenPreview() {
    __THEME_FUNCTION__ {
        HomeScreen()
    }
}
"""

_APP_NAV_HOST = r"""package __PACKAGE__.navigation

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import __PACKAGE__.ui.home.HomeScreen

object Routes {
    const val HOME = "home"
}

@Composable
fun AppNavHost(modifier: Modifier = Modifier) {
    val navController = rememberNavController()

    NavHost(
        navController = navController,
        startDestination = Routes.HOME,
        modifier = modifier,
    ) {
        composable(Routes.HOME) {
            HomeScreen()
        }
    }
}
"""

_GITIGNORE = r"""# Gradle and Android Studio
.gradle/
.kotlin/
build/
.idea/
*.iml
captures/
.externalNativeBuild/
.cxx/

# Machine-specific and secret files: never commit these
local.properties
keystore.properties
*.jks
*.keystore

.DS_Store
"""

_SRC = "app/src/main/java/__PACKAGE_PATH__"
_RES = "app/src/main/res"

FILES: tuple[TemplateFile, ...] = (
    TemplateFile(
        "settings.gradle.kts", _SETTINGS_GRADLE, "Gradle settings: repositories and the :app module"
    ),
    TemplateFile("build.gradle.kts", _ROOT_BUILD_GRADLE, "Root build file: plugin versions"),
    TemplateFile("gradle.properties", _GRADLE_PROPERTIES, "Gradle properties"),
    TemplateFile(
        "gradle/libs.versions.toml", _VERSION_CATALOG, "Version catalog: libraries and plugins"
    ),
    TemplateFile(
        "gradle/wrapper/gradle-wrapper.properties",
        _WRAPPER_PROPERTIES,
        "Gradle wrapper properties (the wrapper jar and scripts are not generated)",
    ),
    TemplateFile("app/build.gradle.kts", _APP_BUILD_GRADLE, "App module build file"),
    TemplateFile("app/proguard-rules.pro", _PROGUARD_RULES, "R8 / ProGuard rules (empty)"),
    TemplateFile(
        "app/src/main/AndroidManifest.xml", _MANIFEST, "Manifest with the launcher activity"
    ),
    TemplateFile(f"{_RES}/values/strings.xml", _STRINGS, "String resources"),
    TemplateFile(f"{_RES}/values/colors.xml", _COLORS, "Color resources"),
    TemplateFile(f"{_RES}/values/themes.xml", _THEMES, "Light window theme"),
    TemplateFile(f"{_RES}/values-night/themes.xml", _THEMES_NIGHT, "Dark window theme"),
    TemplateFile(f"{_SRC}/MainActivity.kt", _MAIN_ACTIVITY, "Launcher activity hosting Compose"),
    TemplateFile(f"{_SRC}/ui/theme/Color.kt", _COLOR_KT, "Compose color palette"),
    TemplateFile(f"{_SRC}/ui/theme/Type.kt", _TYPE_KT, "Compose typography"),
    TemplateFile(f"{_SRC}/ui/theme/Theme.kt", _THEME_KT, "Compose Material 3 theme"),
    TemplateFile(f"{_SRC}/ui/home/HomeScreen.kt", _HOME_SCREEN, "Sample home screen"),
    TemplateFile(
        f"{_SRC}/navigation/AppNavHost.kt", _APP_NAV_HOST, "Navigation host with one destination"
    ),
    TemplateFile(".gitignore", _GITIGNORE, "Git ignore rules for a Gradle Android project"),
)
