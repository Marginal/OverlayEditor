// -*- mode: c -*-

#version 120

void main()
{
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
    gl_FrontColor = gl_Color;
    gl_TexCoord[0].st = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
