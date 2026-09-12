# Add project specific ProGuard rules here.
-keep class com.skymusic.player.parser.model.** { *; }
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
